#!/usr/bin/python
# -*- coding: utf8 -*-

import numpy as np
import pandas as pd
from statsmodels.regression.quantile_regression import QuantReg
from statsmodels.tsa.tsatools import lagmat
from pyFTS.common import SortedCollection, fts
from pyFTS.probabilistic import ProbabilityDistribution


class QuantileRegression(fts.FTS):
    """Façade for statsmodels.regression.quantile_regression"""
    def __init__(self, **kwargs):
        super(QuantileRegression, self).__init__(**kwargs)
        self.name = "QAR"
        self.detail = "Quantile Regression"
        self.is_high_order = True
        self.has_point_forecasting = True
        self.has_interval_forecasting = True
        self.has_probability_forecasting = True
        self.uod_clip = False
        self.benchmark_only = True
        self.min_order = 1
        self.alpha = kwargs.get("alpha", 0.05)
        self.dist = kwargs.get("dist", False)
        self.upper_qt = None
        self.mean_qt = None
        self.lower_qt = None
        self.dist_qt = None

    def train(self, data, **kwargs):
        if self.indexer is not None and isinstance(data, pd.DataFrame):
            data = self.indexer.get_data(data)

        lagdata, ndata = lagmat(data, maxlag=self.order, trim="both", original='sep')

        mqt = QuantReg(ndata, lagdata).fit(0.5)
        if self.alpha is not None:
            uqt = QuantReg(ndata, lagdata).fit(1 - self.alpha)
            lqt = QuantReg(ndata, lagdata).fit(self.alpha)

        self.mean_qt = [k for k in mqt.params]
        if self.alpha is not None:
            self.upper_qt = [k for k in uqt.params]
            self.lower_qt = [k for k in lqt.params]

        if self.dist:
            self.dist_qt = []
            for alpha in np.arange(0.05,0.5,0.05):
                lqt = QuantReg(ndata, lagdata).fit(alpha)
                uqt = QuantReg(ndata, lagdata).fit(1 - alpha)
                lo_qt = [k for k in lqt.params]
                up_qt = [k for k in uqt.params]
                self.dist_qt.append([lo_qt, up_qt])

        self.shortname = "QAR({})-{}".format(self.order,self.alpha)

    def linearmodel(self,data,params):
        #return params[0] + sum([ data[k] * params[k+1] for k in np.arange(0, self.order) ])
        return sum([data[k] * params[k] for k in np.arange(0, self.order)])

    def point_to_interval(self, data, lo_params, up_params):
        lo = self.linearmodel(data, lo_params)
        up = self.linearmodel(data, up_params)
        return [lo, up]

    def interval_to_interval(self, data, lo_params, up_params):
        lo = self.linearmodel([k[0] for k in data], lo_params)
        up = self.linearmodel([k[1] for k in data], up_params)
        return [lo, up]

    def forecast(self, ndata, **kwargs):

        l = len(ndata)

        ret = []

        for k in np.arange(self.order, l+1):   #+1 to forecast one step ahead given all available lags
            sample = ndata[k - self.order : k]

            ret.append(self.linearmodel(sample, self.mean_qt))

        return ret

    def forecast_interval(self, ndata, **kwargs):

        l = len(ndata)

        ret = []

        for k in np.arange(self.order , l):
            sample = ndata[k - self.order: k]
            ret.append(self.point_to_interval(sample, self.lower_qt, self.upper_qt))

        return ret

    def forecast_ahead_interval(self, ndata, steps, **kwargs):

        smoothing = kwargs.get("smoothing", 0.01)

        l = len(ndata)

        ret = []

        nmeans = self.forecast_ahead(ndata, steps, **kwargs)

        for k in np.arange(0, self.order):
            nmeans.insert(k,ndata[k])

        for k in np.arange(self.order, steps+self.order):
            intl = self.point_to_interval(nmeans[k - self.order: k], self.lower_qt, self.upper_qt)

            tmpk = k-self.order

            ret.append([intl[0]*(1 - (tmpk*smoothing)), intl[1]*(1 + (tmpk*smoothing))])

        return ret[-steps:]

    def forecast_distribution(self, ndata, **kwargs):

        ret = []

        l = len(ndata)

        for k in np.arange(self.order, l + 1):
            dist = ProbabilityDistribution.ProbabilityDistribution(type="histogram",
                                                                   uod=[self.original_min, self.original_max])
            intervals = []
            for qt in self.dist_qt:
                sample = ndata[k - self.order: k]
                intl = self.point_to_interval(sample, qt[0], qt[1])
                intervals.append(intl)

            dist.append_interval(intervals)

            ret.append(dist)

        return ret

    def forecast_ahead_distribution(self, ndata, steps, **kwargs):
        smoothing = kwargs.get("smoothing", 0.01)

        l = len(ndata)

        ret = []

        nmeans = self.forecast_ahead(ndata, steps, **kwargs)

        for k in np.arange(0, self.order):
            nmeans.insert(k, ndata[k])

        for k in np.arange(self.order, steps + self.order):
            dist = ProbabilityDistribution.ProbabilityDistribution(type="histogram",
                                                                   uod=[self.original_min, self.original_max])

            intervals = [[nmeans[self.order], nmeans[self.order]]]
            for qt in self.dist_qt:
                intl1 = self.point_to_interval(nmeans[k - self.order: k], qt[0], qt[1])
                tmpk = k - self.order
                intl2 = [intl1[0] * (1 - (tmpk * smoothing)), intl1[1] * (1 + (tmpk * smoothing))]
                intervals.append(intl2)
            dist.append_interval(intervals)

            ret.append(dist)

        return ret

