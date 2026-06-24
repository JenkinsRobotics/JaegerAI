import random
import time
import os

WIDTH = 64
HEIGHT = 32

class Bitmap:
    def __init__(self, width, height):
        self.width = width
        self.height = height
        self.data = [0] * (width * height)
    def __getitem__(self, idx):
        if isinstance(idx, tuple):
            x, y = idx
            return self.data[x + self.width * y]
        return self.data[idx]
    def __setitem__(self, idx, value):
        if isinstance(idx, tuple):
            x, y = idx
            self.data[x + self.width * y] = value
        else:
            self.data[idx] = value

def apply_life_rule(old, new):
    width = old.width
    height = old.height
    for y in range(height):
        yyy = y * width
        ym1 = ((y + height - 1) % height) * width
        yp1 = ((y + 1) % height) * width
        xm1 = width - 1
        for x in range(width):
            xp1 = (x + 1) % width
            neighbors = (
                old[xm1 + ym1] + old[xm1 + yyy] + old[xm1 + yp1] +
                old[x   + ym1] +                  old[x   + yp1] +
                old[xp1 + ym1] + old[xp1 + yyy] + old[xp1 + yp1])
            new[x+yyy] = int(neighbors == 3 or (neighbors == 2 and old[x+yyy]))
            xm1 = x

def randomize(output, fraction=0.33):
    for i in range(output.height * output.width):
        output[i] = int(random.random() < fraction)

def conway(output):
    conway_data = [
        b'  +++   ',
        b'  + +   ',
        b'  + +   ',
        b'   +    ',
        b'+ +++   ',
        b' + + +  ',
        b'   +  + ',
        b'  + +   ',
        b'  + +   ',
    ]
    for i in range(output.height * output.width):
        output[i] = 0
    for i, si in enumerate(conway_data):
        y = output.height - len(conway_data) - 2 + i
        for j, cj in enumerate(si):
            output[(output.width - 8)//2 + j, y] = int(cj == ord(b'+'))

def print_bitmap(bitmap):
    os.system('clear')
    for y in range(bitmap.height):
        row = ''
        for x in range(bitmap.width):
            row += '█' if bitmap[x, y] else ' '
        print(row)

def main():
    b1 = Bitmap(WIDTH, HEIGHT)
    b2 = Bitmap(WIDTH, HEIGHT)
    conway(b1)
    print_bitmap(b1)
    time.sleep(3)
    n = 40
    while True:
        for _ in range(n):
            apply_life_rule(b1, b2)
            print_bitmap(b2)
            time.sleep(0.05)
            apply_life_rule(b2, b1)
            print_bitmap(b1)
            time.sleep(0.05)
        randomize(b1)
        n = 200

if __name__ == "__main__":
    main()
