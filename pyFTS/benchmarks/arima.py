#!/usr/bin/python
# -*- coding: utf8 -*-

import numpy as np
import pandas as pd
from statsmodels.tsa.arima_model import ARIMA as stats_arima
import scipy.stats as st
from pyFTS.common import SortedCollection, fts
from pyFTS.probabilistic import ProbabilityDistribution


class ARIMA(fts.FTS):
    """
    Façade for statsmodels.tsa.arima_model
    """
    def __init__(self, **kwargs):
        super(ARIMA, self).__init__(**kwargs)
        self.name = "ARIMA"
        self.detail = "Auto Regressive Integrated Moving Average"
        self.is_high_order = True
        self.has_point_forecasting = True
        self.has_interval_forecasting = True
        self.has_probability_forecasting = True
        self.uod_clip = False
        self.model = None
        self.model_fit = None
        self.trained_data = None
        self.p = 1
        self.d = 0
        self.q = 0
        self.benchmark_only = True
        self.min_order = 1
        self.alpha = kwargs.get("alpha", 0.05)
        self.order = kwargs.get("order", (1,0,0))
        self._decompose_order(self.order)

    def _decompose_order(self, order):
        if isinstance(order, (tuple, set, list)):
            self.p = order[0]
            self.d = order[1]
            self.q = order[2]
            self.order = self.p + self.q + (self.q - 1 if self.q > 0 else 0)
            self.max_lag = self.order
            self.d = len(self.transformations)
            self.shortname = "ARIMA({},{},{})-{}".format(self.p, self.d, self.q, self.alpha)

    def train(self, data, **kwargs):

        if 'order' in kwargs:
            order = kwargs.pop('order')
            self._decompose_order(order)

        if self.indexer is not None:
            data = self.indexer.get_data(data)

        try:
            self.model =  stats_arima(data, order=(self.p, self.d, self.q))
            self.model_fit = self.model.fit(disp=0)
        except Exception as ex:
            print(ex)
            self.model_fit = None

    def ar(self, data):
        return data.dot(self.model_fit.arparams)

    def ma(self, data):
        return data.dot(self.model_fit.maparams)

    def forecast(self, ndata, **kwargs):
        if self.model_fit is None:
            return np.nan

        ndata = np.array(ndata)

        l = len(ndata)

        ret = []

        ar = np.array([self.ar(ndata[k - self.p: k]) for k in np.arange(self.p, l+1)]) #+1 to forecast one step ahead given all available lags

        if self.q > 0:
            residuals = ndata[self.p-1:] - ar

            ma = np.array([self.ma(residuals[k - self.q: k]) for k in np.arange(self.q, len(residuals) + 1)])

            ret = ar[self.q - 1:] + ma
            ret = ret[self.q:]
        else:
            ret = ar

        #ret = self.apply_inverse_transformations(ret, params=[data[self.order - 1:]])        nforecasts = np.array(forecasts)

        return ret

    def forecast_interval(self, data, **kwargs):

        if self.model_fit is None:
            return np.nan

        if 'alpha' in kwargs:
            alpha = kwargs.get('alpha',0.05)
        else:
            alpha = self.alpha

        sigma = np.sqrt(self.model_fit.sigma2)

        l = len(data)

        ret = []

        for k in np.arange(self.order, l+1):
            tmp = []

            sample = [data[i] for i in np.arange(k - self.order, k)]

            mean = self.forecast(sample)

            if isinstance(mean,(list, np.ndarray)):
                mean = mean[0]

            tmp.append(mean + st.norm.ppf(alpha) * sigma)
            tmp.append(mean + st.norm.ppf(1 - alpha) * sigma)

            ret.append(tmp)

        return ret

    def forecast_ahead_interval(self, ndata, steps, **kwargs):
        if self.model_fit is None:
            return np.nan

        if 'alpha' in kwargs:
            alpha = kwargs.get('alpha',0.05)
        else:
            alpha = self.alpha

        smoothing = kwargs.get("smoothing",0.5)

        sigma = np.sqrt(self.model_fit.sigma2)

        l = len(ndata)

        nmeans = self.forecast_ahead(ndata, steps, **kwargs)

        ret = []

        for k in np.arange(0, steps):
            tmp = []

            hsigma = (1 + k*smoothing)*sigma

            tmp.append(nmeans[k] + st.norm.ppf(alpha) * hsigma)
            tmp.append(nmeans[k] + st.norm.ppf(1 - alpha) * hsigma)

            ret.append(tmp)

        return ret[-steps:]

    def forecast_distribution(self, data, **kwargs):

        sigma = np.sqrt(self.model_fit.sigma2)

        l = len(data)

        ret = []

        for k in np.arange(self.order, l + 1):
            sample = [data[i] for i in np.arange(k - self.order, k)]

            mean = self.forecast(sample)

            if isinstance(mean, (list, np.ndarray)):
                mean = mean[0]

            dist = ProbabilityDistribution.ProbabilityDistribution(type="histogram", uod=[self.original_min, self.original_max])
            intervals = []
            for alpha in np.arange(0.05, 0.5, 0.05):

                qt1 = mean + st.norm.ppf(alpha) * sigma
                qt2 = mean + st.norm.ppf(1 - alpha) * sigma

                intervals.append([qt1, qt2])

            dist.append_interval(intervals)

            ret.append(dist)

        return ret


    def forecast_ahead_distribution(self, data, steps, **kwargs):
        smoothing = kwargs.get("smoothing", 0.5)

        sigma = np.sqrt(self.model_fit.sigma2)

        l = len(data)

        ret = []

        nmeans = self.forecast_ahead(data, steps, **kwargs)

        for k in np.arange(0, steps):
            dist = ProbabilityDistribution.ProbabilityDistribution(type="histogram",
                                                                   uod=[self.original_min, self.original_max])
            intervals = []
            for alpha in np.arange(0.05, 0.5, 0.05):
                tmp = []

                hsigma = (1 + k * smoothing) * sigma

                tmp.append(nmeans[k] + st.norm.ppf(alpha) * hsigma)
                tmp.append(nmeans[k] + st.norm.ppf(1 - alpha) * hsigma)

                intervals.append(tmp)

            dist.append_interval(intervals)

            ret.append(dist)

        return ret[-steps:]

