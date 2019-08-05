# -*- coding: utf-8 -*-
"""A collection of methods for combining detectors
"""
# Author: Yue Zhao <zhaoy@cmu.edu>
# License: BSD 2 clause


import numpy as np

from sklearn.utils import check_array
from sklearn.utils import column_or_1d
from sklearn.utils.validation import check_is_fitted
from pyod.utils.utility import standardizer

from .base import BaseAggregator
from .score_comb import average, maximization, median


class SimpleDetectorAggregator(BaseAggregator):
    """A collection of simple detector combination methods.

    Parameters
    ----------
    base_estimators : list, length must be greater than 1
        Base unsupervised outlier detectors from PyOD. (Note: requires fit and
        decision_function methods)

    method : str, optional (default='average')
        Combination method: {'average', 'maximization',
        'median'}. Pass in weights of detector for weighted version.

    contamination : float in (0., 0.5), optional (default=0.1)
        The amount of contamination of the data set,
        i.e. the proportion of outliers in the data set. Used when fitting to
        define the threshold on the decision function.

    standardization : bool, optional (default=True)
        If True, perform standardization first to convert
        prediction score to zero mean and unit variance.
        See http://scikit-learn.org/stable/auto_examples/preprocessing/plot_scaling_importance.html

    weights : numpy array of shape (1, n_detectors)
        detector weights.

    pre_fitted : bool, optional (default=False)
        Whether the base detectors are trained. If True, `fit`
        process may be skipped.

    Attributes
    ----------
    decision_scores_ : numpy array of shape (n_samples,)
        The outlier scores of the training data.
        The higher, the more abnormal. Outliers tend to have higher
        scores. This value is available once the detector is fitted.

    threshold_ : float
        The threshold is based on ``contamination``. It is the
        ``n_samples * contamination`` most abnormal samples in
        ``decision_scores_``. The threshold is calculated for generating
        binary outlier labels.

    labels_ : int, either 0 or 1
        The binary labels of the training data. 0 stands for inliers
        and 1 for outliers/anomalies. It is generated by applying
        ``threshold_`` on ``decision_scores_``.
    """

    def __init__(self, base_estimators, method='average', contamination=0.1,
                 standardization=True, weights=None, pre_fitted=False):

        super(SimpleDetectorAggregator, self).__init__(
            base_estimators=base_estimators, pre_fitted=pre_fitted)

        # validate input parameters
        if method not in ['average', 'maximization', 'median']:
            raise ValueError("{method} is not a valid parameter.".format(
                method=method))
        self.method = method

        if not (0. < contamination <= 0.5):
            raise ValueError("contamination must be in (0, 0.5], "
                             "got: %f" % contamination)
        self.contamination = contamination

        self.standardization = standardization

        if weights is None:
            self.weights = np.ones([1, self.n_base_estimators_])
        else:

            self.weights = column_or_1d(weights).reshape(1, len(weights))
            assert (self.weights.shape[1] == self.n_base_estimators_)

            # adjust probability by a factor for integrity
            adjust_factor = self.weights.shape[1] / np.sum(weights)
            self.weights = self.weights * adjust_factor

    def fit(self, X, y=None):
        """Fit detector. y is optional for unsupervised methods.

        Parameters
        ----------
        X : numpy array of shape (n_samples, n_features)
            The input samples.

        y : numpy array of shape (n_samples,), optional (default=None)
            The ground truth of the input samples (labels).

        Returns
        -------
        labels_ : numpy array of shape (n_samples,)
            Return the generated labels.

        """

        # Validate inputs X and y
        X = check_array(X)
        self._set_n_classes(y)

        if self.pre_fitted:
            print("Training skipped")
        else:
            for clf in self.base_estimators:
                clf.fit(X, y)
                clf.fitted_ = True

        self.decision_scores_ = self._create_scores(X)
        self._process_decision_scores()

        return self.labels_

    def _create_scores(self, X):
        """Internal function to generate and combine scores.

        Parameters
        ----------
        X : numpy array of shape (n_samples, n_features)
            The input samples.

        Returns
        -------
        agg_score: numpy array of shape (n_samples,)
            Aggregated scores.
        """
        all_scores = np.zeros([X.shape[0], self.n_base_estimators_])

        for i, clf in enumerate(self.base_estimators):
            if hasattr(clf, 'decision_function'):
                all_scores[:, i] = clf.decision_function(X)
            else:
                raise ValueError(
                    "{clf} does not have decision_function.".format(clf=clf))

        if self.standardization:
            all_scores = standardizer(all_scores)
        if self.method == 'average':
            agg_score = average(all_scores, estimator_weights=self.weights)
        if self.method == 'maximization':
            agg_score = maximization(all_scores)
        if self.method == 'median':
            agg_score = median(all_scores)

        return agg_score

    def decision_function(self, X):
        """Predict raw anomaly scores of X using the fitted detector.

        The anomaly score of an input sample is computed based on the fitted
        detector. For consistency, outliers are assigned with
        higher anomaly scores.

        Parameters
        ----------
        X : numpy array of shape (n_samples, n_features)
            The input samples. Sparse matrices are accepted only
            if they are supported by the base estimator.

        Returns
        -------
        anomaly_scores : numpy array of shape (n_samples,)
            The anomaly score of the input samples.
        """

        check_is_fitted(self, ['decision_scores_', 'threshold_', 'labels_'])
        X = check_array(X)

        return self._create_scores(X)

    def predict(self, X):
        """Predict if a particular sample is an outlier or not.

        Parameters
        ----------
        X : numpy array of shape (n_samples, n_features)
            The input samples.

        Returns
        -------
        outlier_labels : numpy array of shape (n_samples,)
            For each observation, tells whether or not
            it should be considered as an outlier according to the
            fitted model. 0 stands for inliers and 1 for outliers.
        """
        check_is_fitted(self, ['decision_scores_', 'threshold_', 'labels_'])
        X = check_array(X)
        return self._detector_predict(X)

    def predict_proba(self, X, proba_method='linear'):
        """Predict the probability of a sample being outlier. Two approaches
        are possible:

        1. simply use Min-max conversion to linearly transform the outlier
           scores into the range of [0,1]. The model must be
           fitted first.
        2. use unifying scores, see :cite:`kriegel2011interpreting`.

        Parameters
        ----------
        X : numpy array of shape (n_samples, n_features)
            The input samples.

        proba_method : str, optional (default='linear')
            Probability conversion method. It must be one of
            'linear' or 'unify'.

        Returns
        -------
        outlier_labels : numpy array of shape (n_samples,)
            For each observation, tells whether or not
            it should be considered as an outlier according to the
            fitted model. Return the outlier probability, ranging
            in [0,1].
        """

        check_is_fitted(self, ['decision_scores_', 'threshold_', 'labels_'])
        X = check_array(X)
        return self._detector_predict_proba(X, proba_method)
