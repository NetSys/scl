import select


class Selector(object):
    '''
    High-level wrapper around the 'select' system call
    '''
    def __init__(self):
        self.__reset()

    def wait(self, inputs, outputs):
        for i in inputs:
            self.inputs.append(i)
        for o in outputs:
            self.outputs.append(o)

    def block(self):
        lists = select.select(self.inputs, self.outputs, [])
        self.__reset()
        return lists

    def __reset(self):
        self.inputs = []
        self.outputs = []
