import os
import time
import random
import numpy as np
import tensorflow as tf
from tensorflow.contrib.keras.python.keras import backend as K
from tensorflow.contrib.keras.python.keras.models import load_model
from tensorflow.contrib.keras.python.keras.optimizers import RMSprop, Adam
from tensorflow.contrib.keras.python.keras.engine import Input, Model
from tensorflow.contrib.keras.python.keras.utils.vis_utils import plot_model
from tensorflow.contrib.keras.python.keras.layers.convolutional import Conv2D
from tensorflow.contrib.keras.python.keras.layers.core import Flatten, Dense, Lambda, Reshape
from rl.dqn_1.Memory import Memory
from rl.dqn_1.settings import settings
from tqdm import tqdm
from os.path import join
from os import listdir


class Algorithm:
    def __init__(self, game, player, representation="image"):
        self.game = game
        self.player = player

        os.makedirs("./output", exist_ok=True)
        os.makedirs("./save", exist_ok=True)
        os.makedirs("./training_data", exist_ok=True)
        checkpoint_path = os.path.join(os.getcwd(), "save")


        self.memory = Memory(settings["memory_size"])

        # Parameters
        self.LEARNING_RATE = settings["learning_rate"]
        self.BATCH_SIZE = settings["batch_size"]
        self.GAMMA = settings["discount_factor"]

        # Epsilon decent
        self.EPSILON_START = settings["epsilon_start"]
        self.EPSILON_END = settings["epsilon_end"]
        self.EPSILON_DECAY = (self.EPSILON_END - self.EPSILON_START) / settings["epsilon_steps"]
        self.epsilon = self.EPSILON_START

        # Exploration parameters (fully random play)
        self.EXPLORATION_WINS = settings["exploration_wins"]
        self.EXPLORATION_WINS_COUNTER = 0

        # Episode data
        self.episode = 0  # Episode Count
        self.episode_loss = 0  # Loss sum of a episode
        self.episode_reward = 0  # Reward sum of a episode
        self.frame = 0  # Frame counter
        self.loss_list = []

        # State data
        self.state = self.game.get_state(self.player, representation=representation)
        self.state_size = self.state[0].shape
        self.state_representation = representation

        # Action data
        self.action_size = len(self.player.action_space)

        # Statistics
        self.q_values = [0 for _ in range(self.action_size)]
        self.action_distribution = [0 for _ in range(self.action_size)]
        self.loss_average = []
        self.train_count = 0

        # Construct Models
        checkpoints = [join(checkpoint_path, file) for file in listdir(checkpoint_path)]
        if settings["load_checkpoint"] and len(checkpoints) > 0:
            last_checkpoint = list(sorted(checkpoints))[-1]
            self.model = load_model(last_checkpoint)
            self.target_model = load_model(last_checkpoint)
        else:
            self.model = self.build_model()
            self.target_model = self.build_model()
        self.graph = tf.get_default_graph()

        # GAN
        if settings["gan"]:
            from rl.dqn_1.GAN import GAN
            self.gan_memory = Memory(settings["memory_size"])
            self.gan = GAN(self.gan_memory, self.graph, self.BATCH_SIZE, self.state_size, self.target_model)

        # Plotting
        if settings["plotting"]:
            from rl.dqn_1.PlotEngine import PlotEngine
            self.plot_losses = PlotEngine(self.game, self)
            self.plot_losses.start()

        # AIConfig
        if settings["ai_config"]:
            from AIConfig import AIConfig
            self.ai_config = AIConfig(self)
            self.ai_config.start()

        # Load training data
        if settings["use_training_data"]:
            for file in tqdm(listdir("./training_data/")):
                file = join("./training_data/", file)
                training_items = np.load(file)
                self.EXPLORATION_WINS_COUNTER += 1
                for training_item in training_items:
                    self.memory.add(training_item)

        self.model.summary()
        print("DQNRUnner inited!")
        print("State size is: %s,%s,%s" % self.state_size)
        print("Action size is: %s" % self.action_size)
        print("Batch size is: %s " % self.BATCH_SIZE)

    def reset(self):

        # Get new initial state
        self.state = self.game.get_state(
            self.player,
            representation=self.state_representation
        )

        # Reset plot
        if settings["plotting"]:
            self.plot_losses.new_game()

        # Update target model
        if self.target_model and self.EXPLORATION_WINS_COUNTER > self.EXPLORATION_WINS:
            self.update_target_model()
            self.save("./save/dqn_p%s_%s.h5" % (self.player.id, int(time.time())))

        # Check if game was a victory
        if self.game.winner == self.player:
            # Add to counter
            print("Exploration: %s/%s" % (self.EXPLORATION_WINS_COUNTER, self.EXPLORATION_WINS))
            self.EXPLORATION_WINS_COUNTER += 1
            items = np.array(self.memory.buffer[-1 * self.frame:])
            np.save("./training_data/win_%s_%s" % (self.EXPLORATION_WINS_COUNTER, time.time()), items)

        # Print output
        print("Episode: %s, Epsilon: %s, Reward: %s, Loss: %s, Memory: %s" % (
            self.episode,
            self.epsilon,
            self.episode_reward,
            self.episode_loss / (self.frame + 1),
            self.memory.count)
              )

        self.frame = 0

        # Reset loss sum
        self.episode_loss = 0

        # Reset episode reward
        self.episode_reward = 0

        # Increase episode
        self.episode += 1

    def update_target_model(self):
        # copy weights from model to target_model
        self.target_model.set_weights(self.model.get_weights())

    def build_model(self):
        # Neural Net for Deep-Q learning Model

        # Image input
        input_layer = Input(shape=self.state_size, name='image_input')
        x = Conv2D(64, (8, 8), strides=(1, 1), padding="same", activation='relu')(input_layer)
        x = Conv2D(64, (4, 4), strides=(1, 1), padding="same", activation='relu')(x)
        x = Conv2D(64, (2, 2), strides=(1, 1), padding="same", activation='relu')(x)
        #x = Conv2D(128, (1, 1), strides=(1, 1), activation='relu', kernel_initializer='uniform')(x)
        #x = Conv2D(256, (3, 3), strides=(2, 2), activation='relu', kernel_initializer='uniform')(x)
        x = Reshape((int(x.shape[1]), int(x.shape[2]), int(x.shape[3])))(x)
        x = Flatten()(x)

        # Value Stream
        vs = Dense(512, activation="relu", kernel_initializer='uniform')(x)
        vs = Dense(1, kernel_initializer='uniform')(vs)

        # Advantage Stream
        ad = Dense(512, activation="relu", kernel_initializer='uniform')(x)
        ad = Dense(self.action_size, kernel_initializer='uniform', activation="linear")(ad)

        policy = Lambda(lambda w: w[0] - K.mean(w[0]) + w[1])([vs, ad])
        #policy = keras.layers.merge([vs, ad], mode=lambda x: x[0] - K.mean(x[0]) + x[1], output_shape=(self.action_size,))

        model = Model(inputs=[input_layer], outputs=[policy])
        optimizer = Adam(lr=self.LEARNING_RATE)
        model.compile(optimizer=optimizer, loss=Algorithm.huber)

        plot_model(model, to_file='./output/_dqn_model.png', show_shapes=True, show_layer_names=True)

        return model

    @staticmethod
    def huber(y_true, y_pred):
        cosh = lambda x: (K.exp(x) + K.exp(-x)) / 2
        return K.mean(K.log(cosh(y_pred - y_true)), axis=-1)

    def load(self, name):
        #self.model.load_weights(name)
        #self.target_model.load_weights(name)
        self.model = load_model(name)
        self.target_model = load_model(name)

    def save(self, name):
        #self.target_model.save_weights(name)
        self.target_model.save(name)

    def train(self):

        if self.memory.count < self.BATCH_SIZE:
            return

        with self.graph.as_default():
            batch_loss = 0
            memories = self.memory.get(self.BATCH_SIZE)
            for s, a, r, s1, terminal in memories:
                # Model = We train on
                # Target = Draw actions from

                target = r

                tar_s = self.target_model.predict(s)
                if not terminal:
                    tar_s1 = self.target_model.predict(s1)
                    target = r + self.GAMMA * np.amax(tar_s1[0])

                tar_s[0][a] = target
                loss = (r + (self.GAMMA * np.amax(tar_s1[0]) - np.amax(tar_s[0]))) ** 2

                history = self.model.fit(s, tar_s, epochs=1, batch_size=1, callbacks=[], verbose=0)
                batch_loss += loss
                self.episode_loss += loss
                self.train_count += 1
            self.loss_list.append(batch_loss)

    def act(self):
        # Epsilon exploration
        if np.random.uniform() <= self.epsilon:
            return random.randrange(self.action_size)

        # Exploit Q-Knowledge
        act_values = self.target_model.predict(self.state)
        self.q_values = act_values[0]

        if settings["gan"]:
            self.gan_memory.add([self.state, self.q_values])

        return np.argmax(act_values[0])

    def reward_fn(self):
        score = ((self.player.health - self.player.opponent.health) / 50) + 0.01
        return score

    def update(self, seconds):
        # 1. Do action
        # 2. Observe
        # 3. Train
        # 4. set state+1 to state

        # Q-Learning
        a = self.act()
        s = self.state
        s1, r, terminal, _ = self.state = self.game.step(
            self.player,
            a,
            representation=self.state_representation,
        )

        r = self.reward_fn()

        # Experience Replay
        self.memory.add([s, a, r, s1, terminal])

        # Increment and save statistics
        self.frame += 1
        self.state = s1
        self.episode_reward += r
        self.action_distribution[a] += 1

        if self.EXPLORATION_WINS_COUNTER < self.EXPLORATION_WINS:
            return

        self.train()
        self.epsilon = max(0, self.epsilon + self.EPSILON_DECAY)

        if settings["gan"]:
            self.gan.train()


