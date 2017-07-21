import math
import random

class Algorithm:


    def __init__(self, game):
        self.game = game

    def init(self):
        pass

    def reset(self):
        pass

    def update(self, seconds):

        action = random.randint(0, len(self.player.action_space) - 1)
        self.player.do_action(action)


    def on_defeat(self):
        pass

    def on_victory(self):
        pass