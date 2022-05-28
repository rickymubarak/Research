"""
Composite Fuzzy Sets
"""

import numpy as np
from pyFTS import *
from pyFTS.common import Membership, FuzzySet


class FuzzySet(FuzzySet.FuzzySet):
    """
    Composite Fuzzy Set
    """
    def __init__(self, name, superset=False, **kwargs):
        """
        Create an empty composite fuzzy set
        :param name: fuzzy set name
        """
        if 'type' in kwargs:
            kwargs.pop('type')
        super(FuzzySet, self).__init__(name, None, None, None, type='composite', **kwargs)
        self.superset = superset
        if self.superset:
            self.sets = []
        else:
            self.mf = []
            self.parameters = []

        self.lower = None
        self.upper = None
        self.centroid = None


    def membership(self, x):
        """
        Calculate the membership value of a given input

        :param x: input value
        :return: membership value of x at this fuzzy set
        """
        if self.superset:
            return max([s.membership(x) for s in self.sets])
        else:
            return min([self.mf[ct](self.transform(x), self.parameters[ct]) for ct in np.arange(0, len(self.mf))])

    def transform(self, x):
        return self.sets[0].transform(x)

    def append(self, mf, parameters):
        """
        Adds a new function to composition

        :param mf:
        :param parameters:
        :return:
        """
        self.mf.append(mf)
        self.parameters.append(parameters)

    def append_set(self, set):
        """
        Adds a new function to composition

        :param mf:
        :param parameters:
        :return:
        """
        self.sets.append(set)

        if self.lower is None or self.lower > set.lower:
            self.lower = set.lower

        if self.upper is None or self.upper < set.upper:
            self.upper = set.upper

        if self.centroid is None or self.centroid < set.centroid:
            self.centroid = set.centroid


    def __str__(self):
        tmp = str([str(k) for k in self.sets])
        return "{}: {}".format(self.name, tmp)


