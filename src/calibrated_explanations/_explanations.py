# pylint: disable=too-many-lines, trailing-whitespace, line-too-long, too-many-public-methods, invalid-name
# flake8: noqa: E501
"""contains the CalibratedExplanations class created by the CalibratedExplainer class
"""
import os

# from pyexpat import features
import warnings
from copy import deepcopy
from abc import ABC, abstractmethod
from time import time
import numpy as np
import matplotlib.pyplot as plt
from ._discretizers import (
    BinaryEntropyDiscretizer,
    EntropyDiscretizer,
    RegressorDiscretizer,
    BinaryRegressorDiscretizer,
)
from .utils import make_directory  # , is_notebook, safe_import


class CalibratedExplanations:  # pylint: disable=too-many-instance-attributes
    """
    A class for storing and visualizing calibrated explanations.
    """

    def __init__(self, calibrated_explainer, test_objects, y_threshold, bins) -> None:
        self.calibrated_explainer = deepcopy(calibrated_explainer)
        self.test_objects = test_objects
        self.y_threshold = y_threshold
        self.low_high_percentiles = None
        self.explanations = []
        self.start_index = 0
        self.current_index = self.start_index
        self.end_index = len(test_objects[:, 0])
        self.bins = bins
        self.total_explain_time = None

    def __iter__(self):
        self.current_index = self.start_index
        return self

    def __next__(self):
        if self.current_index >= self.end_index:
            raise StopIteration
        result = self.get_explanation(self.current_index)
        self.current_index += 1
        return result

    def _is_thresholded(self) -> bool:
        # """test if the explanation is thresholded

        # Returns:
        #     bool: True if the y_threshold is not None
        # """
        return self.y_threshold is not None

    def _is_one_sided(self) -> bool:
        # """test if a regression explanation is one-sided

        # Returns:
        #     bool: True if one of the low or high percentiles is infinite
        # """
        if self.low_high_percentiles is None:
            return False
        return np.isinf(self.get_low_percentile()) or np.isinf(
            self.get_high_percentile()
        )

    def get_confidence(self) -> float:
        """get the confidence of the explanation

        Returns:
            returns the difference between the low and high percentiles
        """
        if np.isinf(self.get_high_percentile()):
            return 100 - self.get_low_percentile()
        if np.isinf(self.get_low_percentile()):
            return self.get_high_percentile()
        return self.get_high_percentile() - self.get_low_percentile()

    def get_low_percentile(self) -> float:
        """get the low percentile of the explanation"""
        return self.low_high_percentiles[0]  # pylint: disable=unsubscriptable-object

    def get_high_percentile(self) -> float:
        """get the high percentile of the explanation"""
        return self.low_high_percentiles[1]  # pylint: disable=unsubscriptable-object

    # pylint: disable=too-many-arguments
    def _finalize(
        self,
        binned,
        feature_weights,
        feature_predict,
        prediction,
        instance_time=None,
        total_time=None,
    ) -> None:
        # """finalize the explanation by adding the binned data and the feature weights
        # """
        for i, instance in enumerate(self.test_objects):
            instance_bin = self.bins[i] if self.bins is not None else None
            if self._is_counterfactual():
                explanation = CounterfactualExplanation(
                    self,
                    i,
                    instance,
                    binned,
                    feature_weights,
                    feature_predict,
                    prediction,
                    self.y_threshold,
                    instance_bin=instance_bin,
                )
            else:
                explanation = FactualExplanation(
                    self,
                    i,
                    instance,
                    binned,
                    feature_weights,
                    feature_predict,
                    prediction,
                    self.y_threshold,
                    instance_bin=instance_bin,
                )
            explanation.explain_time = (
                instance_time[i] if instance_time is not None else None
            )
            self.explanations.append(explanation)
        self.total_explain_time = (
            time() - total_time if total_time is not None else None
        )

    def _get_explainer(self):
        # """get the explainer object
        # """
        return self.calibrated_explainer

    # pylint: disable=too-many-statements, too-many-branches
    def _get_rules(self):
        # """creates counterfactual rules

        # Returns:
        #     List[Dict[str, List]]: a list of dictionaries containing the counterfactual rules, one for each test instance
        # """
        rule_set = []
        for explanation in self.explanations:
            rule_set.append(explanation.get_rules())

    def add_conjunctions(self, n_top_features=5, max_rule_size=2):
        """_summary_

        Args:
            n_top_features (int, optional): the number of most important factual rules to try to combine into conjunctive rules. Defaults to 5.
            max_rule_size (int, optional): the maximum size of the conjunctions. Defaults to 2 (meaning `rule_one and rule_two`).

        Returns:
            CalibratedExplanations: Returns a self reference, to allow for method chaining
        """
        for explanation in self.explanations:
            explanation.remove_conjunctions()
            explanation.add_conjunctions(n_top_features, max_rule_size)
        return self

    def remove_conjunctions(self):
        """removes any conjunctive rules"""
        for explanation in self.explanations:
            explanation.remove_conjunctions()
        return self

    def get_explanation(self, instance_index):
        """The function `get_explanation` returns the explanation corresponding to the instance_index.

        Parameters
        ----------
        instance_index
            The `instance_index` parameter is an integer that represents the index of the explanation
            instance that you want to retrieve. It is used to specify which explanation instance you want to
            get from either the counterfactual rules or the factual rules.

        Returns
        -------
            The method `get_explanation` returns either a CounterfactualExplanation or a FactualExplanation, depending
            on the condition `self._is_counterfactual()`.

        """
        assert isinstance(instance_index, int), "instance_index must be an integer"
        assert instance_index >= 0, "instance_index must be greater than or equal to 0"
        assert instance_index < len(
            self.test_objects
        ), "instance_index must be less than the number of test instances"
        return self.explanations[instance_index]

    def _is_counterfactual(self):
        # '''The function checks if the explanations are counterfactuals by checking if the `discretizer` attribute of the `calibrated_explainer` object is an
        # instance of either `DecileDiscretizer` or `EntropyDiscretizer`.

        # Returns
        # -------
        #     a boolean value indicating whether the explanations are counterfactuals.
        # '''
        return isinstance(
            self.calibrated_explainer.discretizer,
            (RegressorDiscretizer, EntropyDiscretizer),
        )

    # pylint: disable=too-many-arguments
    def plot_all(
        self,
        n_features_to_show=10,
        show=False,
        filename="",
        uncertainty=False,
        interactive=False,
    ):
        """The function `plot_all` plots either counterfactual or factual explanations for a given
        instance, with the option to show or save the plots.

        Parameters
        ----------
        n_features_to_show, optional
            The parameter "n_features_to_show" determines the number of top features to display in the
            plot. It specifies how many of the most important features should be shown in the plot.
        show, optional
            The "show" parameter determines whether the plots should be displayed immediately after they
            are generated. If set to True, the plots will be shown; if set to False, the plots will not be
            shown.
        filename : str, default=''
            The filename parameter is a string that represents the full path and filename of the plot
            image file that will be saved. If this parameter is not provided or is an empty string, the plot
            will not be saved as an image file. The index of each explanation will be appended to the
            filename (e.g. filename0.png, filename1.png, etc.).
        uncertainty, optional
            The "uncertainty" parameter is a boolean flag that determines whether to include uncertainty
            information in the plots. If set to True, the plots will show uncertainty measures, if
            available, along with the explanations. If set to False, the plots will only show the
            explanations without uncertainty information. Only applicable to factual explanations.

        """
        if len(filename) > 0:
            path = os.path.dirname(filename) + "/"
            filename = os.path.basename(filename)
            title, ext = os.path.splitext(filename)
            make_directory(path, save_ext=np.array([ext]))
        for index, explanation in enumerate(self.explanations):
            if len(filename) > 0:
                filename = path + title + str(index) + ext
            explanation.plot_explanation(
                n_features_to_show=n_features_to_show,
                show=show,
                filename=filename,
                uncertainty=uncertainty,
                interactive=interactive,
            )

    # pylint: disable=too-many-arguments
    def plot_explanation(
        self,
        instance_index,
        n_features_to_show=10,
        show=False,
        filename="",
        uncertainty=False,
        interactive=False,
    ):
        """This function plots the explanation for a given instance using either factual or
        counterfactual plots.

        Parameters
        ----------
        instance_index : int
            The index of the instance for which you want to plot the  explanation.
        n_features_to_show : int, default=10
            The `n_features_to_show` parameter determines the number of top features to display in the
            plot. If set to `None`, it will show all the features. Otherwise, it will show the specified
            number of features, up to the total number of features available.
        show : bool, default=False
            A boolean parameter that determines whether the plot should be displayed or not. If set to
            True, the plot will be displayed. If set to False, the plot will not be displayed.
        filename : str, default=''
            The filename parameter is a string that represents the full path and filename of the plot
            image file that will be saved. If this parameter is not provided or is an empty string, the plot
            will not be saved as an image file.
        uncertainty : bool, default=False
            Only applicable if factual explanation. The `uncertainty` parameter is a boolean flag that determines whether to plot the uncertainty
            intervals for the feature weights. If `uncertainty` is set to `True`, the plot will show the
            range of possible feature weights based on the lower and upper bounds of the uncertainty
            intervals. If `uncertainty` is set to `False`, the plot will only show the feature weights

        """
        factual = self.get_explanation(instance_index)
        factual.plot_explanation(
            n_features_to_show=n_features_to_show,
            show=show,
            filename=filename,
            uncertainty=uncertainty,
            interactive=interactive,
        )

    # pylint: disable=too-many-arguments
    def plot_factual(
        self,
        instance_index,
        n_features_to_show=10,
        show=False,
        filename="",
        uncertainty=False,
        interactive=False,
    ):
        """This function plots the factual explanation for a given instance using either probabilistic or
        regression plots.

        Parameters
        ----------
        instance_index : int
            The index of the instance for which you want to plot the factual explanation.
        n_features_to_show : int, default=10
            The `n_features_to_show` parameter determines the number of top features to display in the
            plot. If set to `None`, it will show all the features. Otherwise, it will show the specified
            number of features, up to the total number of features available.
        show : bool, default=False
            A boolean parameter that determines whether the plot should be displayed or not. If set to
            True, the plot will be displayed. If set to False, the plot will not be displayed.
        filename : str, default=''
            The filename parameter is a string that represents the full path and filename of the plot
            image file that will be saved. If this parameter is not provided or is an empty string, the plot
            will not be saved as an image file.
        uncertainty : bool, default=False
            The `uncertainty` parameter is a boolean flag that determines whether to plot the uncertainty
            intervals for the feature weights. If `uncertainty` is set to `True`, the plot will show the
            range of possible feature weights based on the lower and upper bounds of the uncertainty
            intervals. If `uncertainty` is set to `False`, the plot will only show the feature weights

        """
        factual = self.get_explanation(instance_index)
        factual.plot_explanation(
            n_features_to_show=n_features_to_show,
            show=show,
            filename=filename,
            uncertainty=uncertainty,
            interactive=interactive,
        )

    def plot_counterfactual(
        self,
        instance_index,
        n_features_to_show=10,
        show=False,
        filename="",
        interactive=False,
    ):
        """The function `plot_counterfactual` plots the counterfactual explanation for a given instance in
        a dataset.

        Parameters
        ----------
        instance_index : int
            The index of the instance for which you want to plot the counterfactual explanation.
        n_features_to_show : int, default=10
            The `n_features_to_show` parameter determines the number of top features to display in the
            plot. If set to `None`, it will show all the features. Otherwise, it will show the specified
            number of features, up to the total number of features available.
        show : bool, default=False
            A boolean parameter that determines whether the plot should be displayed or not. If set to
            True, the plot will be displayed. If set to False, the plot will not be displayed.
        filename : str, default=''
            The filename parameter is a string that represents the full path and filename of the plot
            image file that will be saved. If this parameter is not provided or is an empty string, the plot
            will not be saved as an image file.

        """
        counterfactual = self.get_explanation(instance_index)
        counterfactual.plot_explanation(
            n_features_to_show=n_features_to_show,
            show=show,
            filename=filename,
            interactive=interactive,
        )

    # pylint: disable=protected-access
    def as_lime(self, num_features_to_show=None):
        """transforms the explanation into a lime explanation object

        Returns:
            list of lime.Explanation : list of lime explanation objects with the same values as the CalibratedExplanations
        """
        _, lime_exp = (
            self.calibrated_explainer._preload_lime()
        )  # pylint: disable=protected-access
        exp = []
        for explanation in self.explanations:  # range(len(self.test_objects[:,0])):
            tmp = deepcopy(lime_exp)
            tmp.intercept[1] = 0
            tmp.local_pred = explanation.prediction["predict"]
            if "regression" in self.calibrated_explainer.mode:
                tmp.predicted_value = explanation.prediction["predict"]
                tmp.min_value = np.min(self.calibrated_explainer.cal_y)
                tmp.max_value = np.max(self.calibrated_explainer.cal_y)
            else:
                tmp.predict_proba[0], tmp.predict_proba[1] = (
                    1 - explanation.prediction["predict"],
                    explanation.prediction["predict"],
                )

            feature_weights = explanation.feature_weights["predict"]
            num_to_show = (
                num_features_to_show
                if num_features_to_show is not None
                else self.calibrated_explainer.num_features
            )
            features_to_plot = explanation._rank_features(
                feature_weights, num_to_show=num_to_show
            )
            rules = explanation._define_conditions()
            for j, f in enumerate(
                features_to_plot[::-1]
            ):  # pylint: disable=invalid-name
                tmp.local_exp[1][j] = (f, feature_weights[f])
            del tmp.local_exp[1][num_to_show:]
            tmp.domain_mapper.discretized_feature_names = rules
            tmp.domain_mapper.feature_values = explanation.test_object
            exp.append(tmp)
        return exp

    def as_shap(self):
        """transforms the explanation into a shap explanation object

        Returns:
            shap.Explanation : shap explanation object with the same values as the explanation
        """
        _, shap_exp = self.calibrated_explainer._preload_shap(
            len(self.test_objects[:, 0])
        )  # pylint: disable=protected-access
        for i, explanation in enumerate(
            self.explanations
        ):  # range(len(self.test_objects[:,0])):
            shap_exp.base_values[i] = explanation.prediction["predict"]
            for f in range(len(self.test_objects[0, :])):
                shap_exp.values[i][f] = -explanation.feature_weights["predict"][f]
        return shap_exp


# pylint: disable=too-many-instance-attributes, too-many-locals, too-many-arguments
class CalibratedExplanation(ABC):
    """
    A class for storing and visualizing calibrated explanations.
    """

    def __init__(
        self,
        calibrated_explanations,
        instance_index,
        test_object,
        binned,
        feature_weights,
        feature_predict,
        prediction,
        y_threshold=None,
        instance_bin=None,
    ):
        self.calibrated_explanations = calibrated_explanations
        self.instance_index = instance_index
        self.test_object = test_object
        self.binned = {}
        self.feature_weights = {}
        self.feature_predict = {}
        self.prediction = {}
        for key in binned.keys():
            self.binned[key] = deepcopy(binned[key][instance_index])
        for key in feature_weights.keys():
            self.feature_weights[key] = deepcopy(feature_weights[key][instance_index])
            self.feature_predict[key] = deepcopy(feature_predict[key][instance_index])
        for key in prediction.keys():
            self.prediction[key] = deepcopy(prediction[key][instance_index])
        self.y_threshold = (
            y_threshold
            if np.isscalar(y_threshold)
            else None if y_threshold is None else y_threshold[instance_index]
        )

        self.conditions = []
        self.rules = []
        self.conjunctive_rules = []
        self._has_rules = False
        self._has_conjunctive_rules = False
        self.bin = [instance_bin] if instance_bin is not None else None
        self.explain_time = None

    def _get_explainer(self):
        return (
            self.calibrated_explanations._get_explainer()
        )  # pylint: disable=protected-access

    def _rank_features(self, feature_weights, width=None, num_to_show=None):
        if num_to_show is None or num_to_show > len(feature_weights):
            num_to_show = len(feature_weights)
        # handle case where there are same weight but different uncertainty
        if width is not None:
            # get the indeces by first sorting on the absolute value of the
            # feature_weight and then on the width
            sorted_indices = [
                i
                for i, x in sorted(
                    enumerate(list(zip(np.abs(feature_weights), -width))),
                    key=lambda x: (x[1][0], x[1][1]),
                )
            ]
        else:
            sorted_indices = np.argsort(np.abs(feature_weights))
        return sorted_indices[
            -num_to_show:
        ]  # pylint: disable=invalid-unary-operand-type

    def _is_one_sided(self) -> bool:
        # """test if a regression explanation is one-sided

        # Returns:
        #     bool: True if one of the low or high percentiles is infinite
        # """
        if self.calibrated_explanations.low_high_percentiles is None:
            return False
        return np.isinf(self.calibrated_explanations.get_low_percentile()) or np.isinf(
            self.calibrated_explanations.get_high_percentile()
        )

    def _is_thresholded(self) -> bool:
        # """test if the explanation is thresholded

        # Returns:
        #     bool: True if the y_threshold is not None
        # """
        return self.y_threshold is not None

    @abstractmethod
    def plot_explanation(self, n_features_to_show=None, **kwargs):
        """The function `plot_explanation` plots either counterfactual or factual explanations for a given
        instance, with the option to show or save the plots.
        """
        # pass

    @abstractmethod
    def add_conjunctions(self, n_top_features=5, max_rule_size=2):
        """The function `add_conjunctions` adds conjunctive rules to the factual or counterfactual
        explanations. The conjunctive rules are added to the `conjunctive_rules` attribute of the
        `CalibratedExplanations` object.
        """
        # pass

    @abstractmethod
    def _check_preconditions(self):
        pass

    @abstractmethod
    def _get_rules(self):
        pass

    def remove_conjunctions(self):
        """removes any conjunctive rules"""
        self._has_conjunctive_rules = False
        return self

    def _define_conditions(self):
        # """defines the rule conditions for an instance

        # Args:
        #     instance (n_features,): a test instance

        # Returns:
        #     list[str]: a list of conditioins for each feature in the instance
        # """
        self.conditions = []
        # pylint: disable=invalid-name
        x = self._get_explainer().discretizer.discretize(self.test_object)
        for f in range(self._get_explainer().num_features):
            if f in self._get_explainer().categorical_features:
                if self._get_explainer().categorical_labels is not None:
                    try:
                        target = self._get_explainer().categorical_labels[f][int(x[f])]
                        rule = f"{self._get_explainer().feature_names[f]} = {target}"
                    except IndexError:
                        rule = f"{self._get_explainer().feature_names[f]} = {x[f]}"
                else:
                    rule = f"{self._get_explainer().feature_names[f]} = {x[f]}"
            else:
                rule = self._get_explainer().discretizer.names[f][int(x[f])]
            self.conditions.append(rule)
        return self.conditions

    def _predict_conjunctive(
        self,
        rule_value_set,
        original_features,
        perturbed,
        threshold,  # pylint: disable=invalid-name, too-many-locals, too-many-arguments
        predicted_class,
        bins=None,
    ):
        # """support function to calculate the prediction for a conjunctive rule
        # """
        rule_predict, rule_low, rule_high, rule_count = 0, 0, 0, 0
        if len(original_features) == 2:
            of1, of2 = original_features[0], original_features[1]
            rule_value1, rule_value2 = rule_value_set[0], rule_value_set[1]
        elif len(original_features) >= 3:
            of1, of2, of3 = (
                original_features[0],
                original_features[1],
                original_features[2],
            )
            rule_value1, rule_value2, rule_value3 = (
                rule_value_set[0],
                rule_value_set[1],
                rule_value_set[2],
            )
        for value_1 in rule_value1:
            perturbed[of1] = value_1
            for value_2 in rule_value2:
                perturbed[of2] = value_2
                if len(original_features) >= 3:
                    for value_3 in rule_value3:
                        perturbed[of3] = value_3
                        p_value, low, high, _ = self._get_explainer()._predict(
                            perturbed.reshape(
                                1, -1
                            ),  # pylint: disable=protected-access
                            threshold=threshold,
                            low_high_percentiles=self.calibrated_explanations.low_high_percentiles,
                            classes=predicted_class,
                            bins=bins,
                        )
                        rule_predict += p_value[0]
                        rule_low += low[0]
                        rule_high += high[0]
                        rule_count += 1
                else:
                    p_value, low, high, _ = self._get_explainer()._predict(
                        perturbed.reshape(1, -1),  # pylint: disable=protected-access
                        threshold=threshold,
                        low_high_percentiles=self.calibrated_explanations.low_high_percentiles,
                        classes=predicted_class,
                        bins=bins,
                    )
                    rule_predict += p_value[0]
                    rule_low += low[0]
                    rule_high += high[0]
                    rule_count += 1
        rule_predict /= rule_count
        rule_low /= rule_count
        rule_high /= rule_count
        return rule_predict, rule_low, rule_high

    # pylint: disable=protected-access, unused-argument
    def predict_new(self, rule_idx, new_value, is_lesser=True):
        """
        The function `_predict_new` predicts a new threshold value of a feature in a rule.
        """
        print(f"_predict_new{rule_idx, new_value}")
        # collection = self.calibrated_explanations
        # f = rule_idx
        # lesser = new_value
        # perturbed = deepcopy(self.test_object)

        # rule_value = []
        # num_bins = 2
        # average_predict, low_predict, high_predict, counts = np.zeros(num_bins),np.zeros(num_bins),np.zeros(num_bins),np.zeros(num_bins)

        # bin_value = 0
        # if is_lesser:
        #     lesser = new_value
        #     lesser_values = np.unique(self._get_explainer().__get_lesser_values(f, lesser))
        #     rule_value.append(lesser_values)
        #     for value in lesser_values:
        #         perturbed[f] = value
        #         predict, low, high, _ = self._get_explainer()._predict(perturbed.reshape(1,-1), threshold=self.y_threshold, low_high_percentiles=collection.low_high_percentiles, classes=self.prediction['predict'], bins=self.bin)
        #         average_predict[bin_value] += predict[0]
        #         low_predict[bin_value] += low[0]
        #         high_predict[bin_value] += high[0]
        #     average_predict[bin_value] = average_predict[bin_value]/len(lesser_values)
        #     low_predict[bin_value] = low_predict[bin_value]/len(lesser_values)
        #     high_predict[bin_value] = high_predict[bin_value]/len(lesser_values)
        #     counts[bin_value] = len(np.where(self._get_explainer().cal_X[:,f] < lesser)[0])
        #     bin_value += 1
        # else:
        #     greater = new_value
        #     greater_values = np.unique(self._get_explainer().__get_greater_values(f, greater))
        #     rule_value.append(greater_values)
        #     for value in greater_values:
        #         perturbed[f] = value
        #         predict, low, high, _ = self._get_explainer()._predict(perturbed.reshape(1,-1), threshold=self.y_threshold, low_high_percentiles=collection.low_high_percentiles, classes=self.prediction['predict'], bins=self.bin)
        #         average_predict[bin_value] += predict[0]
        #         low_predict[bin_value] += low[0]
        #         high_predict[bin_value] += high[0]
        #     average_predict[bin_value] = average_predict[bin_value]/len(greater_values)
        #     low_predict[bin_value] = low_predict[bin_value]/len(greater_values)
        #     high_predict[bin_value] = high_predict[bin_value]/len(greater_values)
        #     counts[bin_value] = len(np.where(self._get_explainer().cal_X[:,f] > greater)[0])
        #     bin_value += 1

        # covered_values = self._get_explainer().__get_covered_values(f, lesser, greater)
        # rule_value.append(covered_values)
        # for value in covered_values:
        #     perturbed[f] = value
        #     predict, low, high, _ = self._get_explainer()._predict(perturbed.reshape(1,-1), threshold=self.y_threshold, low_high_percentiles=collection.low_high_percentiles, classes=self.prediction['predict'], bins=self.bin)
        #     average_predict[bin_value] += predict[0]
        #     low_predict[bin_value] += low[0]
        #     high_predict[bin_value] += high[0]
        # average_predict[bin_value] = average_predict[bin_value]/len(covered_values)
        # low_predict[bin_value] = low_predict[bin_value]/len(covered_values)
        # high_predict[bin_value] = high_predict[bin_value]/len(covered_values)
        # counts[bin_value] = len(np.where((self._get_explainer().cal_X[:,f] >= lesser) & (self._get_explainer().cal_X[:,f] <= greater))[0])
        # current_bin = bin_value

        # rule_values[f] = (rule_value, x_original[f], perturbed_original[0,f])
        # uncovered = np.setdiff1d(np.arange(len(average_predict)), current_bin)

        # fractions = counts[uncovered]/np.sum(counts[uncovered])

        # instance_binned['predict'].append(average_predict)
        # instance_binned['low'].append(low_predict)
        # instance_binned['high'].append(high_predict)
        # instance_binned['current_bin'].append(current_bin)
        # instance_binned['counts'].append(counts)
        # instance_binned['fractions'].append(fractions)

        # # Handle the situation where the current bin is the only bin
        # if len(uncovered) == 0:
        #     instance_predict['predict'][f] = 0
        #     instance_predict['low'][f] = 0
        #     instance_predict['high'][f] = 0

        #     instance_weights['predict'][f] = 0
        #     instance_weights['low'][f] = 0
        #     instance_weights['high'][f] = 0
        # else:
        #     # Calculate the weighted average (only makes a difference for categorical features)
        #     # instance_predict['predict'][f] = np.sum(average_predict[uncovered]*fractions[uncovered])
        #     # instance_predict['low'][f] = np.sum(low_predict[uncovered]*fractions[uncovered])
        #     # instance_predict['high'][f] = np.sum(high_predict[uncovered]*fractions[uncovered])
        #     instance_predict['predict'][f] = np.mean(average_predict[uncovered])
        #     instance_predict['low'][f] = np.mean(low_predict[uncovered])
        #     instance_predict['high'][f] = np.mean(high_predict[uncovered])

        #     instance_weights['predict'][f] = self._assign_weight(instance_predict['predict'][f], prediction['predict'][-1], is_probabilistic)
        #     tmp_low = self._assign_weight(instance_predict['low'][f], prediction['predict'][-1], is_probabilistic)
        #     tmp_high = self._assign_weight(instance_predict['high'][f], prediction['predict'][-1], is_probabilistic)
        #     instance_weights['low'][f] = np.min([tmp_low, tmp_high])
        #     instance_weights['high'][f] = np.max([tmp_low, tmp_high])
        #         test_X,
        #         threshold = None, # The same meaning as threshold has for cps in crepes.
        #         low_high_percentiles = (5, 95),
        #         classes = None,
        #         bins = None,
        #         ):
        # rule_predict, rule_low, rule_high = self._get_explainer()._predict(rule_values,
        #                                                         original_features,
        #                                                         ,
        #                                                         threshold,
        #                                                         predicted_class,
        #                                                         bins=self.bin)

        return rule_idx, new_value

    @abstractmethod
    def _get_slider_values(self, index, rule_name):
        """gets the slider values for a feature or rule

        Args:
            index (int): the index of the feature or rule

        Returns:
            min: lowest value of the slider
            max: highest value of the slider
            step: step size of the slider
            value: initial value of the slider
        """


# pylint: disable=too-many-instance-attributes, too-many-locals, too-many-arguments
class FactualExplanation(CalibratedExplanation):
    """
    A class for storing and visualizing factual explanations.
    """

    def __init__(
        self,
        calibrated_explanations,
        instance_index,
        test_object,
        binned,
        feature_weights,
        feature_predict,
        prediction,
        y_threshold=None,
        instance_bin=None,
    ):
        super().__init__(
            calibrated_explanations,
            instance_index,
            test_object,
            binned,
            feature_weights,
            feature_predict,
            prediction,
            y_threshold,
            instance_bin,
        )
        self._check_preconditions()
        self._get_rules()

    def _get_slider_values(self, index, rule_name):
        assert (
            index not in self._get_explainer().categorical_features
        ), "categorical features cannot be selected for adaption"

        if "<" in rule_name:
            index = [
                i
                for i, item in enumerate(
                    self._get_explainer().discretizer.names.values()
                )
                if item[0] == rule_name
            ][0]
            value = self._get_explainer().discretizer.mins[index][1]
            min_value = self.test_object[index]
            max_value = np.max(self._get_explainer().cal_X[:, index])
        else:
            index = [
                i
                for i, item in enumerate(
                    self._get_explainer().discretizer.names.values()
                )
                if item[1] == rule_name
            ][0]
            value = self._get_explainer().discretizer.mins[index][1]
            min_value = np.min(self._get_explainer().cal_X[:, index])
            max_value = self.test_object[index]
        cal_X = self._get_explainer().cal_X
        uniques = np.unique(
            cal_X[[min_value < x <= max_value for x in cal_X[:, index]], index]
        )
        value_selection = [
            (uniques[i] + uniques[i + 1]) / 2 for i in range(len(uniques) - 1)
        ]  # find thresholds between actual values
        value = min(
            value_selection, key=lambda x: abs(x - value)
        )  # find value in slider closest to rule condition
        # print(rule_name, min_value, max_value, value, value_selection)
        return value_selection, value

    def _check_preconditions(self):
        if "regression" in self._get_explainer().mode:
            if not isinstance(
                self._get_explainer().discretizer, BinaryRegressorDiscretizer
            ):
                warnings.warn(
                    "Factual explanations for regression recommend using the binaryRegressor "
                    + "discretizer. Consider extracting factual explanations using "
                    + "`explainer.explain_factual(test_set)`"
                )
        else:
            if not isinstance(
                self._get_explainer().discretizer, BinaryEntropyDiscretizer
            ):
                warnings.warn(
                    "Factual explanations for classification recommend using the "
                    + "binaryEntropy discretizer. Consider extracting factual "
                    + "explanations using `explainer.explain_factual(test_set)`"
                )

    def _get_rules(self):
        # """creates factual rules

        # Returns:
        #     List[Dict[str, List]]: a list of dictionaries containing the factual rules, one for each test instance
        # """
        if self._has_conjunctive_rules:
            return self.conjunctive_rules
        if self._has_rules:
            return self.rules
        self._has_rules = False
        # i = self.instance_index
        instance = deepcopy(self.test_object)
        factual = {
            "base_predict": [],
            "base_predict_low": [],
            "base_predict_high": [],
            "predict": [],
            "predict_low": [],
            "predict_high": [],
            "weight": [],
            "weight_low": [],
            "weight_high": [],
            "value": [],
            "rule": [],
            "feature": [],
            "feature_value": [],
            "classes": None,
            "is_conjunctive": [],
        }
        factual["classes"] = self.prediction["classes"]
        factual["base_predict"].append(self.prediction["predict"])
        factual["base_predict_low"].append(self.prediction["low"])
        factual["base_predict_high"].append(self.prediction["high"])
        rules = self._define_conditions()
        for f, _ in enumerate(instance):  # pylint: disable=invalid-name
            if self.prediction["predict"] == self.feature_predict["predict"][f]:
                continue
            factual["predict"].append(self.feature_predict["predict"][f])
            factual["predict_low"].append(self.feature_predict["low"][f])
            factual["predict_high"].append(self.feature_predict["high"][f])
            factual["weight"].append(self.feature_weights["predict"][f])
            factual["weight_low"].append(self.feature_weights["low"][f])
            factual["weight_high"].append(self.feature_weights["high"][f])
            if f in self._get_explainer().categorical_features:
                if self._get_explainer().categorical_labels is not None:
                    factual["value"].append(
                        self._get_explainer().categorical_labels[f][int(instance[f])]
                    )
                else:
                    factual["value"].append(str(instance[f]))
            else:
                factual["value"].append(str(np.around(instance[f], decimals=2)))
            factual["rule"].append(rules[f])
            factual["feature"].append(f)
            factual["feature_value"].append(self.binned["rule_values"][f][0][-1])
            factual["is_conjunctive"].append(False)
        self.rules = factual
        self._has_rules = True
        return self.rules

    # pylint: disable=too-many-locals, too-many-branches, too-many-statements
    def add_conjunctions(self, n_top_features=5, max_rule_size=2, prune=True):
        # """adds conjunctive factual rules

        # Args:
        #     n_top_features (int, optional): the number of most important factual rules to try to combine into conjunctive rules. Defaults to 5.
        #     max_rule_size (int, optional): the maximum size of the conjunctions. Defaults to 2 (meaning `rule_one and rule_two`).

        # Returns:
        #     CalibratedExplanations: Returns a self reference, to allow for method chaining
        # """
        if max_rule_size >= 4:
            raise ValueError("max_rule_size must be 2 or 3")
        if max_rule_size < 2:
            return self
        if not self._has_rules:
            factual = deepcopy(self._get_rules())
        else:
            factual = deepcopy(self.rules)
        if self._has_conjunctive_rules:
            conjunctive = self.conjunctive_rules
        else:
            conjunctive = deepcopy(factual)
        self._has_conjunctive_rules = False
        self.conjunctive_rules = []
        i = self.instance_index
        # pylint: disable=unsubscriptable-object, invalid-name
        threshold = None if self.y_threshold is None else self.y_threshold
        x_original = deepcopy(self.test_object)

        num_rules = len(factual["rule"])
        predicted_class = factual["classes"]
        conjunctive["classes"] = predicted_class
        if n_top_features is None:
            n_top_features = num_rules
        top_conjunctives = self._rank_features(
            np.reshape(conjunctive["weight"], (len(conjunctive["weight"]))),
            width=np.reshape(
                np.array(conjunctive["weight_high"])
                - np.array(conjunctive["weight_low"]),
                (len(conjunctive["weight"])),
            ),
            num_to_show=np.min([num_rules, n_top_features]),
        )

        covered_features = []
        covered_combinations = [
            conjunctive["feature"][i] for i in range(len(conjunctive["rule"]))
        ]
        for f1, cf1 in enumerate(factual["feature"]):  # cf = factual feature
            covered_features.append(cf1)
            of1 = factual["feature"][f1]  # of = original feature
            rule_value1 = (
                factual["feature_value"][f1]
                if isinstance(factual["feature_value"][f1], np.ndarray)
                else [factual["feature_value"][f1]]
            )
            for _, cf2 in enumerate(top_conjunctives):  # cf = conjunctive feature
                if cf2 in covered_features:
                    continue
                rule_values = [rule_value1]
                original_features = [of1]
                if conjunctive["is_conjunctive"][cf2]:
                    of2 = conjunctive["feature"][cf2]
                    if of1 in of2:
                        continue
                    for of in of2:
                        original_features.append(of)
                    for rule_value in conjunctive["feature_value"][cf2]:
                        rule_values.append(rule_value)
                else:
                    of2 = conjunctive["feature"][cf2]  # of = original feature
                    if of1 == of2:
                        continue
                    original_features.append(of2)
                    rule_values.append(
                        conjunctive["feature_value"][cf2]
                        if isinstance(conjunctive["feature_value"][cf2], np.ndarray)
                        else [conjunctive["feature_value"][cf2]]
                    )
                skip = False
                for ofs in covered_combinations:
                    try:
                        if np.all(np.sort(original_features) == ofs):
                            skip = True
                            break
                    except ValueError:
                        pass
                if skip:
                    continue
                covered_combinations.append(np.sort(original_features))

                rule_predict, rule_low, rule_high = self._predict_conjunctive(
                    rule_values,
                    original_features,
                    deepcopy(x_original),
                    threshold,
                    predicted_class,
                    bins=self.bin,
                )

                conjunctive["predict"].append(rule_predict)
                conjunctive["predict_low"].append(rule_low)
                conjunctive["predict_high"].append(rule_high)
                conjunctive["weight"].append(rule_predict - self.prediction["predict"])
                conjunctive["weight_low"].append(
                    rule_low - self.prediction["predict"]
                    if rule_low != -np.inf
                    else -np.inf
                )
                conjunctive["weight_high"].append(
                    rule_high - self.prediction["predict"]
                    if rule_high != np.inf
                    else np.inf
                )
                conjunctive["value"].append(
                    factual["value"][f1] + "\n" + conjunctive["value"][cf2]
                )
                conjunctive["feature"].append(original_features)
                conjunctive["feature_value"].append(rule_values)
                conjunctive["rule"].append(
                    factual["rule"][f1] + " & \n" + conjunctive["rule"][cf2]
                )
                if prune:
                    conjunctive["is_conjunctive"].append(True)
                else:
                    conjunctive["is_conjunctive"].append(True)
        self.conjunctive_rules = conjunctive
        self._has_conjunctive_rules = True
        return self.add_conjunctions(
            n_top_features=n_top_features, max_rule_size=max_rule_size - 1
        )

    def plot_factual(
        self,
        n_features_to_show=None,
        show=False,
        filename="",
        uncertainty=False,
        interactive=False,
    ):
        """The function `plot_factual` plots the factual explanation for a given instance using either
        probabilistic or regression plots.
        """
        self.plot_explanation(
            n_features_to_show=n_features_to_show,
            show=show,
            filename=filename,
            uncertainty=uncertainty,
            interactive=interactive,
        )

    # pylint: disable=consider-iterating-dictionary
    def plot_explanation(self, n_features_to_show=None, **kwargs):
        """This function plots the factual explanation for a given instance using either probabilistic or
        regression plots.

        Parameters
        ----------
        instance_index : int
            The index of the instance for which you want to plot the factual explanation.
        n_features_to_show : int, default=10
            The `n_features_to_show` parameter determines the number of top features to display in the
            plot. If set to `None`, it will show all the features. Otherwise, it will show the specified
            number of features, up to the total number of features available.
        show : bool, default=False
            A boolean parameter that determines whether the plot should be displayed or not. If set to
            True, the plot will be displayed. If set to False, the plot will not be displayed.
        filename : str, default=''
            The filename parameter is a string that represents the full path and filename of the plot
            image file that will be saved. If this parameter is not provided or is an empty string, the plot
            will not be saved as an image file.
        uncertainty : bool, default=False
            The `uncertainty` parameter is a boolean flag that determines whether to plot the uncertainty
            intervals for the feature weights. If `uncertainty` is set to `True`, the plot will show the
            range of possible feature weights based on the lower and upper bounds of the uncertainty
            intervals. If `uncertainty` is set to `False`, the plot will only show the feature weights

        """
        show = kwargs["show"] if "show" in kwargs.keys() else False
        filename = kwargs["filename"] if "filename" in kwargs.keys() else ""
        uncertainty = kwargs["uncertainty"] if "uncertainty" in kwargs.keys() else False
        interactive = kwargs["interactive"] if "interactive" in kwargs.keys() else False

        factual = self._get_rules()  # get_explanation(instance_index)
        self._check_preconditions()
        predict = self.prediction
        num_features_to_show = len(factual["weight"])
        if n_features_to_show is None:
            n_features_to_show = num_features_to_show
        n_features_to_show = np.min([num_features_to_show, n_features_to_show])

        if len(filename) > 0:
            path = os.path.dirname(filename) + "/"
            filename = os.path.basename(filename)
            title, ext = os.path.splitext(filename)
            make_directory(path, save_ext=np.array([ext]))
            path = "plots/" + path
            save_ext = [ext]
        else:
            path = ""
            title = ""
            save_ext = []
        if uncertainty:
            feature_weights = {
                "predict": factual["weight"],
                "low": factual["weight_low"],
                "high": factual["weight_high"],
            }
        else:
            feature_weights = factual["weight"]
        width = np.reshape(
            np.array(factual["weight_high"]) - np.array(factual["weight_low"]),
            (len(factual["weight"])),
        )
        features_to_plot = self._rank_features(
            factual["weight"], width=width, num_to_show=n_features_to_show
        )
        column_names = factual["rule"]
        if "classification" in self._get_explainer().mode or self._is_thresholded():
            self.__plot_probabilistic(
                factual["value"],
                predict,
                feature_weights,
                features_to_plot,
                n_features_to_show,
                column_names,
                title=title,
                path=path,
                interval=uncertainty,
                show=show,
                idx=self.instance_index,
                save_ext=save_ext,
                interactive=interactive,
            )
        else:
            self.__plot_regression(
                factual["value"],
                predict,
                feature_weights,
                features_to_plot,
                n_features_to_show,
                column_names,
                title=title,
                path=path,
                interval=uncertainty,
                show=show,
                idx=self.instance_index,
                save_ext=save_ext,
                interactive=interactive,
            )

    # pylint: disable=dangerous-default-value, unused-argument
    def __plot_probabilistic(
        self,
        instance,
        predict,
        feature_weights,
        features_to_plot,
        num_to_show,
        column_names,
        title,
        path,
        show,
        interval=False,
        idx=None,
        save_ext=["svg", "pdf", "png"],
        interactive=False,
    ):
        """plots regular and uncertainty explanations"""
        if interval is True:
            assert idx is not None
        fig = plt.figure(figsize=(10, num_to_show * 0.5 + 2))
        subfigs = fig.subfigures(3, 1, height_ratios=[1, 1, num_to_show + 2])

        if interval and (self._is_one_sided()):
            raise Warning("Interval plot is not supported for one-sided explanations.")

        ax_positive = subfigs[0].add_subplot(111)
        ax_negative = subfigs[1].add_subplot(111)

        ax_main = subfigs[2].add_subplot(111)

        # plot the probabilities at the top
        x = np.linspace(0, 1, 2)
        xj = np.linspace(x[0] - 0.2, x[0] + 0.2, 2)
        p = predict["predict"]
        pl = (
            predict["low"]
            if predict["low"] != -np.inf
            else np.min(self._get_explainer().cal_y)
        )
        ph = (
            predict["high"]
            if predict["high"] != np.inf
            else np.max(self._get_explainer().cal_y)
        )

        ax_negative.fill_betweenx(xj, 1 - p, 1 - p, color="b")
        ax_negative.fill_betweenx(xj, 0, 1 - ph, color="b")
        ax_negative.fill_betweenx(xj, 1 - pl, 1 - ph, color="b", alpha=0.2)
        ax_negative.set_xlim([0, 1])
        ax_negative.set_yticks(range(1))
        ax_negative.set_xticks(np.linspace(0, 1, 6))
        ax_positive.fill_betweenx(xj, p, p, color="r")
        ax_positive.fill_betweenx(xj, 0, pl, color="r")
        ax_positive.fill_betweenx(xj, pl, ph, color="r", alpha=0.2)
        ax_positive.set_xlim([0, 1])
        ax_positive.set_yticks(range(1))
        ax_positive.set_xticks([])

        if self._is_thresholded():
            if np.isscalar(self.y_threshold):
                ax_negative.set_yticklabels(
                    labels=[f"P(y>{float(self.y_threshold) :.2f})"]
                )
                ax_positive.set_yticklabels(
                    labels=[f"P(y<={float(self.y_threshold) :.2f})"]
                )
            else:
                ax_negative.set_yticklabels(
                    labels=[f"P(y>{float(self.y_threshold) :.2f})"]
                )  # pylint: disable=unsubscriptable-object
                ax_positive.set_yticklabels(
                    labels=[f"P(y<={float(self.y_threshold) :.2f})"]
                )  # pylint: disable=unsubscriptable-object
        else:
            if self._get_explainer().class_labels is not None:
                if (
                    self._get_explainer()._is_multiclass()
                ):  # pylint: disable=protected-access
                    ax_negative.set_yticklabels(
                        labels=[
                            f'P(y!={self._get_explainer().class_labels[self.prediction["classes"]]})'
                        ]
                    )  # pylint: disable=line-too-long
                    ax_positive.set_yticklabels(
                        labels=[
                            f'P(y={self._get_explainer().class_labels[self.prediction["classes"]]})'
                        ]
                    )  # pylint: disable=line-too-long
                else:
                    ax_negative.set_yticklabels(
                        labels=[f"P(y={self._get_explainer().class_labels[0]})"]
                    )  # pylint: disable=line-too-long
                    ax_positive.set_yticklabels(
                        labels=[f"P(y={self._get_explainer().class_labels[1]})"]
                    )  # pylint: disable=line-too-long
            else:
                if (
                    self._get_explainer()._is_multiclass()
                ):  # pylint: disable=protected-access
                    ax_negative.set_yticklabels(
                        labels=[f'P(y!={self.prediction["classes"]})']
                    )
                    ax_positive.set_yticklabels(
                        labels=[f'P(y={self.prediction["classes"]})']
                    )
                else:
                    ax_negative.set_yticklabels(labels=["P(y=0)"])
                    ax_positive.set_yticklabels(labels=["P(y=1)"])
        ax_negative.set_xlabel("Probability")

        # Plot the base prediction in black/grey
        if num_to_show > 0:
            x = np.linspace(0, num_to_show - 1, num_to_show)
            xl = np.linspace(-0.5, x[0] if len(x) > 0 else 0, 2)
            xh = np.linspace(x[-1], x[-1] + 0.5 if len(x) > 0 else 0.5, 2)
            ax_main.fill_betweenx(x, [0], [0], color="k")
            ax_main.fill_betweenx(xl, [0], [0], color="k")
            ax_main.fill_betweenx(xh, [0], [0], color="k")
            if interval:
                p = predict["predict"]
                gwl = predict["low"] - p
                gwh = predict["high"] - p

                gwh, gwl = np.max([gwh, gwl]), np.min([gwh, gwl])
                ax_main.fill_betweenx(
                    [-0.5, num_to_show - 0.5], gwl, gwh, color="k", alpha=0.2
                )

            # For each feature, plot the weight
            for jx, j in enumerate(features_to_plot):
                xj = np.linspace(x[jx] - 0.2, x[jx] + 0.2, 2)
                min_val, max_val = 0, 0
                if interval:
                    width = feature_weights["predict"][j]
                    wl = feature_weights["low"][j]
                    wh = feature_weights["high"][j]
                    wh, wl = np.max([wh, wl]), np.min([wh, wl])
                    max_val = wh if width < 0 else 0
                    min_val = wl if width > 0 else 0
                    # If uncertainty cover zero, then set to 0 to avoid solid plotting
                    if wl < 0 < wh:
                        min_val = 0
                        max_val = 0
                else:
                    width = feature_weights[j]
                    min_val = width if width < 0 else 0
                    max_val = width if width > 0 else 0
                color = "r" if width > 0 else "b"
                ax_main.fill_betweenx(xj, min_val, max_val, color=color)
                if interval:
                    if wl < 0 < wh and self._get_explainer().mode == "classification":
                        ax_main.fill_betweenx(xj, 0, wl, color="b", alpha=0.2)
                        ax_main.fill_betweenx(xj, wh, 0, color="r", alpha=0.2)
                    else:
                        ax_main.fill_betweenx(xj, wl, wh, color=color, alpha=0.2)

            ax_main.set_yticks(range(num_to_show))
            (
                ax_main.set_yticklabels(
                    labels=[column_names[i] for i in features_to_plot]
                )
                if column_names is not None
                else ax_main.set_yticks(range(num_to_show))
            )  # pylint: disable=expression-not-assigned
            ax_main.set_ylim(-0.5, x[-1] + 0.5 if len(x) > 0 else 0.5)
            ax_main.set_ylabel("Rules")
            ax_main.set_xlabel("Feature weights")
            ax_main_twin = ax_main.twinx()
            ax_main_twin.set_yticks(range(num_to_show))
            ax_main_twin.set_yticklabels([instance[i] for i in features_to_plot])
            ax_main_twin.set_ylim(-0.5, x[-1] + 0.5 if len(x) > 0 else 0.5)
            ax_main_twin.set_ylabel("Instance values")
        for ext in save_ext:
            fig.savefig(path + title + ext, bbox_inches="tight")
        if show:
            fig.show()

        # if interactive:
        #     # rewrite the code below to exclude categorical features, start with the most important
        #     # pylint: disable=missing-function-docstring, missing-class-docstring, protected-access
        #     class interactive_context:
        #         def __init__(self, explanation) -> None:
        #             self.selected_rule_idx = [i for i in features_to_plot if i not in explanation._get_explainer().categorical_features][-1]
        #             self.selected_name = column_names[self.selected_rule_idx]
        #             self.possible_values, self.selected_value = explanation._get_slider_values(self.selected_rule_idx, self.selected_name)
        #             self.explanation = explanation
        #         def update(self, rule_name, value):
        #             print(rule_name, self.selected_name, value, self.selected_value, self.selected_rule_idx)
        #             if rule_name != self.selected_name:
        #                 self.selected_rule_idx = [i for i, item in enumerate(column_names) if item == rule_name][0]
        #                 self.selected_name = column_names[self.selected_rule_idx]
        #                 self.possible_values, self.selected_value = self.explanation._get_slider_values(self.selected_rule_idx, self.selected_name)
        #                 # print(self.selected_name, self.selected_value, self.possible_values)
        #                 value_slider.description = self.selected_name
        #                 value_slider.options = self.possible_values
        #                 value_slider.value = self.selected_value
        #             else:
        #                 if self.selected_value == value:
        #                     return
        #                 # evaluate a new instance with the adjusted rule threshold
        #                 self.explanation.predict_new(self.selected_rule_idx, value)
        #     context = interactive_context(self)
        #     if is_notebook():
        #         widgets = safe_import('ipywidgets')

        #         # categorical attributes cannot (and need not) be changed
        #         rules = widgets.Dropdown(options=[column_names[i] for i in [i for i in features_to_plot if i not in self._get_explainer().categorical_features][::-1]], value=context.selected_name, description='Select rule')
        #         value_slider = widgets.SelectionSlider(options=context.possible_values, value=context.selected_value, description=context.selected_name)
        #         widgets.interact(context.update, rule_name=rules, value=value_slider)

    # pylint: disable=dangerous-default-value, too-many-branches, too-many-statements, unused-argument
    def __plot_regression(
        self,
        instance,
        predict,
        feature_weights,
        features_to_plot,
        num_to_show,
        column_names,
        title,
        path,
        show,
        interval=False,
        idx=None,
        save_ext=["svg", "pdf", "png"],
        interactive=False,
    ):
        """plots regular and uncertainty explanations"""
        if interval is True:
            assert idx is not None
        fig = plt.figure(figsize=(10, num_to_show * 0.5 + 2))
        subfigs = fig.subfigures(2, 1, height_ratios=[1, num_to_show + 2])

        if interval and (self._is_one_sided()):
            raise Warning("Interval plot is not supported for one-sided explanations.")

        ax_regression = subfigs[0].add_subplot(111)
        ax_main = subfigs[1].add_subplot(111)

        # plot the probabilities at the top
        x = np.linspace(0, 1, 2)
        xj = np.linspace(x[0] - 0.2, x[0] + 0.2, 2)
        p = predict["predict"]
        pl = (
            predict["low"]
            if predict["low"] != -np.inf
            else np.min(self._get_explainer().cal_y)
        )
        ph = (
            predict["high"]
            if predict["high"] != np.inf
            else np.max(self._get_explainer().cal_y)
        )

        ax_regression.fill_betweenx(xj, pl, ph, color="r", alpha=0.2)
        ax_regression.fill_betweenx(xj, p, p, color="r")
        ax_regression.set_xlim(
            [
                np.min([pl, np.min(self._get_explainer().cal_y)]),
                np.max([ph, np.max(self._get_explainer().cal_y)]),
            ]
        )
        ax_regression.set_yticks(range(1))

        ax_regression.set_xlabel(
            f"Prediction interval with {self.calibrated_explanations.get_confidence()}% confidence"
        )
        ax_regression.set_yticklabels(labels=["Median prediction"])

        # Plot the base prediction in black/grey
        x = np.linspace(0, num_to_show - 1, num_to_show)
        xl = np.linspace(-0.5, x[0], 2)
        xh = np.linspace(x[-1], x[-1] + 0.5, 2)
        ax_main.fill_betweenx(x, [0], [0], color="k")
        ax_main.fill_betweenx(xl, [0], [0], color="k")
        ax_main.fill_betweenx(xh, [0], [0], color="k")
        x_min, x_max = 0, 0
        if interval:
            p = predict["predict"]
            gwl = p - predict["low"]
            gwh = p - predict["high"]

            gwh, gwl = np.max([gwh, gwl]), np.min([gwh, gwl])
            # ax_main.fill_betweenx([-0.5,num_to_show-0.5], gwl, gwh, color='k', alpha=0.2)

            x_min, x_max = gwl, gwh
        # For each feature, plot the weight
        for jx, j in enumerate(features_to_plot):
            xj = np.linspace(x[jx] - 0.2, x[jx] + 0.2, 2)
            min_val, max_val = 0, 0
            if interval:
                width = feature_weights["predict"][j]
                wl = feature_weights["low"][j]
                wh = feature_weights["high"][j]
                wh, wl = np.max([wh, wl]), np.min([wh, wl])
                max_val = wh if width < 0 else 0
                min_val = wl if width > 0 else 0
                # If uncertainty cover zero, then set to 0 to avoid solid plotting
                if wl < 0 < wh:
                    min_val = 0
                    max_val = 0
            else:
                width = feature_weights[j]
                min_val = width if width < 0 else 0
                max_val = width if width > 0 else 0
            color = "b" if width > 0 else "r"
            ax_main.fill_betweenx(xj, min_val, max_val, color=color)
            if interval:
                ax_main.fill_betweenx(xj, wl, wh, color=color, alpha=0.2)

                x_min = np.min([x_min, min_val, max_val, wl, wh])
                x_max = np.max([x_max, min_val, max_val, wl, wh])
            else:
                x_min = np.min([x_min, min_val, max_val])
                x_max = np.max([x_max, min_val, max_val])

        ax_main.set_yticks(range(num_to_show))
        (
            ax_main.set_yticklabels(labels=[column_names[i] for i in features_to_plot])
            if column_names is not None
            else ax_main.set_yticks(range(num_to_show))
        )  # pylint: disable=expression-not-assigned
        ax_main.set_ylim(-0.5, x[-1] + 0.5 if len(x) > 0 else 0.5)
        ax_main.set_ylabel("Rules")
        ax_main.set_xlabel("Feature weights")
        ax_main.set_xlim(x_min, x_max)
        ax_main_twin = ax_main.twinx()
        ax_main_twin.set_yticks(range(num_to_show))
        ax_main_twin.set_yticklabels([instance[i] for i in features_to_plot])
        ax_main_twin.set_ylim(-0.5, x[-1] + 0.5 if len(x) > 0 else 0.5)
        ax_main_twin.set_ylabel("Instance values")
        for ext in save_ext:
            fig.savefig(path + title + ext, bbox_inches="tight")
        if show:
            fig.show()


class CounterfactualExplanation(CalibratedExplanation):
    """This class represents a counterfactual explanation for a given instance. It is a subclass of
    `CalibratedExplanation` and inherits all its properties and methods.
    """

    def __init__(
        self,
        calibrated_explanations,
        instance_index,
        test_object,
        binned,
        feature_weights,
        feature_predict,
        prediction,
        y_threshold=None,
        instance_bin=None,
    ):
        super().__init__(
            calibrated_explanations,
            instance_index,
            test_object,
            binned,
            feature_weights,
            feature_predict,
            prediction,
            y_threshold,
            instance_bin,
        )
        self._check_preconditions()
        self._get_rules()

    def _get_slider_values(self, index, rule_name):
        assert (
            index not in self._get_explainer().categorical_features
        ), "categorical features cannot be selected for adaption"

        if "<" in rule_name:
            value = self._get_explainer().discretizer.mins[index][1]
            min_value = np.min(self._get_explainer().cal_X[:, index])
            max_value = self.test_object[index]
        else:
            value = self._get_explainer().discretizer.maxs[index][1]
            min_value = self.test_object[index]
            max_value = np.max(self._get_explainer().cal_X[:, index])
        cal_X = self._get_explainer().cal_X
        num_values = len(
            np.unique(
                cal_X[[min_value <= x < max_value for x in cal_X[:, index]], index],
                return_counts=True,
            )
        )
        print(
            rule_name,
            min_value,
            max_value,
            num_values,
            (max_value - min_value) / num_values,
            value,
        )
        return min_value, max_value, (max_value - min_value) / num_values, value

    def _check_preconditions(self):
        if "regression" in self._get_explainer().mode:
            if not isinstance(self._get_explainer().discretizer, RegressorDiscretizer):
                warnings.warn(
                    "Counterfactual explanations for regression recommend using the "
                    + "regressor discretizer. Consider extracting counterfactual "
                    + "explanations using `explainer.explain_counterfactual(test_set)`"
                )
        else:
            if not isinstance(self._get_explainer().discretizer, EntropyDiscretizer):
                warnings.warn(
                    "Counterfactual explanations for classification recommend using "
                    + "the entropy discretizer. Consider extracting counterfactual "
                    + "explanations using `explainer.explain_counterfactual(test_set)`"
                )

    # pylint: disable=too-many-statements, too-many-branches
    def _get_rules(self):
        # """creates counterfactual rules

        # Returns:
        #     List[Dict[str, List]]: a list of dictionaries containing the counterfactual rules, one for each test instance
        # """
        if self._has_conjunctive_rules:
            return self.conjunctive_rules
        if self._has_rules:
            return self.rules
        self.rules = []
        self.labels = {}  # pylint: disable=attribute-defined-outside-init
        instance = deepcopy(self.test_object)
        discretized = self._get_explainer()._discretize(
            deepcopy(instance).reshape(1, -1)
        )[
            0
        ]  # pylint: disable=protected-access
        instance_predict = self.binned["predict"]
        instance_low = self.binned["low"]
        instance_high = self.binned["high"]
        counterfactual = {
            "base_predict": [],
            "base_predict_low": [],
            "base_predict_high": [],
            "predict": [],
            "predict_low": [],
            "predict_high": [],
            "weight": [],
            "weight_low": [],
            "weight_high": [],
            "value": [],
            "rule": [],
            "feature": [],
            "feature_value": [],
            "classes": None,
            "is_conjunctive": [],
        }

        counterfactual["classes"] = self.prediction["classes"]
        counterfactual["base_predict"].append(self.prediction["predict"])
        counterfactual["base_predict_low"].append(self.prediction["low"])
        counterfactual["base_predict_high"].append(self.prediction["high"])
        rule_boundaries = self._get_explainer().rule_boundaries(deepcopy(instance))
        for f, _ in enumerate(instance):  # pylint: disable=invalid-name
            if f in self._get_explainer().categorical_features:
                values = np.array(self._get_explainer().feature_values[f])
                values = np.delete(values, values == discretized[f])
                for value_bin, value in enumerate(values):
                    if self.prediction["predict"] == instance_predict[f][value_bin]:
                        continue
                    counterfactual["predict"].append(instance_predict[f][value_bin])
                    counterfactual["predict_low"].append(instance_low[f][value_bin])
                    counterfactual["predict_high"].append(instance_high[f][value_bin])
                    counterfactual["weight"].append(
                        instance_predict[f][value_bin] - self.prediction["predict"]
                    )
                    counterfactual["weight_low"].append(
                        instance_low[f][value_bin] - self.prediction["predict"]
                        if instance_low[f][value_bin] != -np.inf
                        else instance_low[f][value_bin]
                    )
                    counterfactual["weight_high"].append(
                        instance_high[f][value_bin] - self.prediction["predict"]
                        if instance_high[f][value_bin] != np.inf
                        else instance_high[f][value_bin]
                    )
                    if self._get_explainer().categorical_labels is not None:
                        counterfactual["value"].append(
                            self._get_explainer().categorical_labels[f][
                                int(instance[f])
                            ]
                        )
                    else:
                        counterfactual["value"].append(
                            str(np.around(instance[f], decimals=2))
                        )
                    counterfactual["feature"].append(f)
                    counterfactual["feature_value"].append(value)
                    if self._get_explainer().categorical_labels is not None:
                        self.labels[len(counterfactual["rule"])] = f
                        counterfactual["rule"].append(
                            f"{self._get_explainer().feature_names[f]} = "
                            + f"{self._get_explainer().categorical_labels[f][int(value)]}"
                        )
                    else:
                        counterfactual["rule"].append(
                            f"{self._get_explainer().feature_names[f]} = {value}"
                        )
                    counterfactual["is_conjunctive"].append(False)
            else:
                values = np.array(self._get_explainer().cal_X[:, f])
                lesser = rule_boundaries[f][0]
                greater = rule_boundaries[f][1]

                value_bin = 0
                if np.any(values < lesser):
                    if self.prediction["predict"] == np.mean(
                        instance_predict[f][value_bin]
                    ):
                        continue
                    counterfactual["predict"].append(
                        np.mean(instance_predict[f][value_bin])
                    )
                    counterfactual["predict_low"].append(
                        np.mean(instance_low[f][value_bin])
                    )
                    counterfactual["predict_high"].append(
                        np.mean(instance_high[f][value_bin])
                    )
                    counterfactual["weight"].append(
                        np.mean(instance_predict[f][value_bin])
                        - self.prediction["predict"]
                    )
                    counterfactual["weight_low"].append(
                        np.mean(instance_low[f][value_bin]) - self.prediction["predict"]
                        if instance_low[f][value_bin] != -np.inf
                        else instance_low[f][value_bin]
                    )
                    counterfactual["weight_high"].append(
                        np.mean(instance_high[f][value_bin])
                        - self.prediction["predict"]
                        if instance_high[f][value_bin] != np.inf
                        else instance_high[f][value_bin]
                    )
                    counterfactual["value"].append(
                        str(np.around(instance[f], decimals=2))
                    )
                    counterfactual["feature"].append(f)
                    counterfactual["feature_value"].append(
                        self.binned["rule_values"][f][0][0]
                    )
                    counterfactual["rule"].append(
                        f"{self._get_explainer().feature_names[f]} < {lesser:.2f}"
                    )
                    counterfactual["is_conjunctive"].append(False)
                    value_bin = 1

                if np.any(values > greater):
                    if self.prediction["predict"] == np.mean(
                        instance_predict[f][value_bin]
                    ):
                        continue
                    counterfactual["predict"].append(
                        np.mean(instance_predict[f][value_bin])
                    )
                    counterfactual["predict_low"].append(
                        np.mean(instance_low[f][value_bin])
                    )
                    counterfactual["predict_high"].append(
                        np.mean(instance_high[f][value_bin])
                    )
                    counterfactual["weight"].append(
                        np.mean(instance_predict[f][value_bin])
                        - self.prediction["predict"]
                    )
                    counterfactual["weight_low"].append(
                        np.mean(instance_low[f][value_bin]) - self.prediction["predict"]
                        if instance_low[f][value_bin] != -np.inf
                        else instance_low[f][value_bin]
                    )
                    counterfactual["weight_high"].append(
                        np.mean(instance_high[f][value_bin])
                        - self.prediction["predict"]
                        if instance_high[f][value_bin] != np.inf
                        else instance_high[f][value_bin]
                    )
                    counterfactual["value"].append(
                        str(np.around(instance[f], decimals=2))
                    )
                    counterfactual["feature"].append(f)
                    counterfactual["feature_value"].append(
                        self.binned["rule_values"][f][0][
                            1 if len(self.binned["rule_values"][f][0]) == 3 else 0
                        ]
                    )
                    counterfactual["rule"].append(
                        f"{self._get_explainer().feature_names[f]} > {greater:.2f}"
                    )
                    counterfactual["is_conjunctive"].append(False)

        self.rules = counterfactual
        self._has_rules = True
        return self.rules

    # pylint: disable=too-many-locals
    def add_conjunctions(self, n_top_features=5, max_rule_size=2):
        # """adds conjunctive counterfactual rules

        # Args:
        #     n_top_features (int, optional): the number of most important counterfactual rules to try to combine into conjunctive rules. Defaults to 5.
        #     max_rule_size (int, optional): the maximum size of the conjunctions. Defaults to 2 (meaning `rule_one and rule_two`).

        # Returns:
        #     CalibratedExplanations: Returns a self reference, to allow for method chaining
        # """
        if max_rule_size >= 4:
            raise ValueError("max_rule_size must be 2 or 3")
        if max_rule_size < 2:
            return self
        if not self._has_rules:
            counterfactual = deepcopy(self._get_rules())
        else:
            counterfactual = deepcopy(self.rules)
        if self._has_conjunctive_rules:
            conjunctive = self.conjunctive_rules
        else:
            conjunctive = deepcopy(counterfactual)
        if self._has_conjunctive_rules:
            return self
        self.conjunctive_rules = []
        # pylint: disable=unsubscriptable-object, invalid-name
        threshold = None if self.y_threshold is None else self.y_threshold
        x_original = deepcopy(self.test_object)

        num_rules = len(counterfactual["rule"])
        predicted_class = counterfactual["classes"]
        conjunctive["classes"] = predicted_class
        if n_top_features is None:
            n_top_features = num_rules
        top_conjunctives = self._rank_features(
            np.reshape(conjunctive["weight"], (len(conjunctive["weight"]))),
            width=np.reshape(
                np.array(conjunctive["weight_high"])
                - np.array(conjunctive["weight_low"]),
                (len(conjunctive["weight"])),
            ),
            num_to_show=np.min([num_rules, n_top_features]),
        )

        covered_features = []
        covered_combinations = [
            conjunctive["feature"][i] for i in range(len(conjunctive["rule"]))
        ]
        for f1, cf1 in enumerate(counterfactual["feature"]):  # cf = factual feature
            covered_features.append(cf1)
            of1 = counterfactual["feature"][f1]  # of = original feature
            rule_value1 = (
                counterfactual["feature_value"][f1]
                if isinstance(counterfactual["feature_value"][f1], np.ndarray)
                else [counterfactual["feature_value"][f1]]
            )
            for _, cf2 in enumerate(top_conjunctives):  # cf = conjunctive feature
                if cf2 in covered_features:
                    continue
                rule_values = [rule_value1]
                original_features = [of1]
                if conjunctive["is_conjunctive"][cf2]:
                    of2 = conjunctive["feature"][cf2]
                    if of1 in of2:
                        continue
                    for of in of2:
                        original_features.append(of)
                    for rule_value in conjunctive["feature_value"][cf2]:
                        rule_values.append(rule_value)
                else:
                    of2 = conjunctive["feature"][cf2]  # of = original feature
                    if of1 == of2:
                        continue
                    original_features.append(of2)
                    rule_values.append(
                        conjunctive["feature_value"][cf2]
                        if isinstance(conjunctive["feature_value"][cf2], np.ndarray)
                        else [conjunctive["feature_value"][cf2]]
                    )
                skip = False
                for ofs in covered_combinations:
                    if np.all(np.sort(original_features) == ofs):
                        skip = True
                        break
                if skip:
                    continue
                covered_combinations.append(np.sort(original_features))

                rule_predict, rule_low, rule_high = self._predict_conjunctive(
                    rule_values,
                    original_features,
                    deepcopy(x_original),
                    threshold,
                    predicted_class,
                    bins=self.bin,
                )
                conjunctive["predict"].append(rule_predict)
                conjunctive["predict_low"].append(rule_low)
                conjunctive["predict_high"].append(rule_high)
                conjunctive["weight"].append(rule_predict - self.prediction["predict"])
                conjunctive["weight_low"].append(
                    rule_low - self.prediction["predict"]
                    if rule_low != -np.inf
                    else -np.inf
                )
                conjunctive["weight_high"].append(
                    rule_high - self.prediction["predict"]
                    if rule_high != np.inf
                    else np.inf
                )
                conjunctive["value"].append(
                    counterfactual["value"][f1] + "\n" + conjunctive["value"][cf2]
                )
                conjunctive["feature"].append(original_features)
                conjunctive["feature_value"].append(rule_values)
                conjunctive["rule"].append(
                    counterfactual["rule"][f1] + " & \n" + conjunctive["rule"][cf2]
                )
                conjunctive["is_conjunctive"].append(True)
        self.conjunctive_rules = conjunctive
        self._has_conjunctive_rules = True
        return self.add_conjunctions(
            n_top_features=n_top_features, max_rule_size=max_rule_size - 1
        )

    # pylint: disable=consider-iterating-dictionary
    def plot_counterfactual(
        self, n_features_to_show=None, show=False, filename="", interactive=False
    ):
        """The function `plot_counterfactual` plots the counterfactual explanation for a given instance in
        a dataset.
        """
        self.plot_explanation(
            n_features_to_show=n_features_to_show,
            show=show,
            filename=filename,
            interactive=interactive,
        )

    # pylint: disable=consider-iterating-dictionary
    def plot_explanation(self, n_features_to_show=None, **kwargs):
        """The function `plot_counterfactual` plots the counterfactual explanation for a given instance in
        a dataset.

        Parameters
        ----------
        instance_index : int
            The index of the instance for which you want to plot the counterfactual explanation.
        n_features_to_show : int, default=10
            The `n_features_to_show` parameter determines the number of top features to display in the
            plot. If set to `None`, it will show all the features. Otherwise, it will show the specified
            number of features, up to the total number of features available.
        show : bool, default=False
            A boolean parameter that determines whether the plot should be displayed or not. If set to
            True, the plot will be displayed. If set to False, the plot will not be displayed.
        filename : str, default=''
            The filename parameter is a string that represents the full path and filename of the plot
            image file that will be saved. If this parameter is not provided or is an empty string, the plot
            will not be saved as an image file.

        """
        show = kwargs["show"] if "show" in kwargs.keys() else False
        filename = kwargs["filename"] if "filename" in kwargs.keys() else ""
        interactive = kwargs["interactive"] if "interactive" in kwargs.keys() else False

        counterfactual = self._get_rules()  # get_explanation(instance_index)
        self._check_preconditions()
        predict = self.prediction
        if len(filename) > 0:
            path = os.path.dirname(filename) + "/"
            filename = os.path.basename(filename)
            title, ext = os.path.splitext(filename)
            make_directory(path, save_ext=np.array([ext]))
            path = "plots/" + path
            save_ext = [ext]
        else:
            path = ""
            title = ""
            save_ext = []
        feature_predict = {
            "predict": counterfactual["predict"],
            "low": counterfactual["predict_low"],
            "high": counterfactual["predict_high"],
        }
        feature_weights = np.reshape(
            counterfactual["weight"], (len(counterfactual["weight"]))
        )
        width = np.reshape(
            np.array(counterfactual["weight_high"])
            - np.array(counterfactual["weight_low"]),
            (len(counterfactual["weight"])),
        )
        num_rules = len(counterfactual["rule"])
        if n_features_to_show is None:
            n_features_to_show = num_rules
        num_to_show_ = np.min([num_rules, n_features_to_show])
        features_to_plot = self._rank_features(
            feature_weights, width=width, num_to_show=num_to_show_
        )
        column_names = counterfactual["rule"]
        self.__plot_counterfactual(
            counterfactual["value"],
            predict,
            feature_predict,
            features_to_plot,
            num_to_show=num_to_show_,
            column_names=column_names,
            title=title,
            path=path,
            show=show,
            save_ext=save_ext,
            interactive=interactive,
        )

    # pylint: disable=dangerous-default-value, too-many-arguments, too-many-locals, invalid-name, too-many-branches, too-many-statements, unused-argument
    def __plot_counterfactual(
        self,
        instance,
        predict,
        feature_predict,
        features_to_plot,
        num_to_show,
        column_names,
        title,
        path,
        show,
        save_ext=["svg", "pdf", "png"],
        interactive=False,
    ):
        """plots counterfactual explanations"""
        fig = plt.figure(figsize=(10, num_to_show * 0.5))
        ax_main = fig.add_subplot(111)

        x = np.linspace(0, num_to_show - 1, num_to_show)
        p_l = (
            predict["low"]
            if predict["low"] != -np.inf
            else np.min(self._get_explainer().cal_y)
        )
        p_h = (
            predict["high"]
            if predict["high"] != np.inf
            else np.max(self._get_explainer().cal_y)
        )
        p = predict["predict"]
        venn_abers = {"low_high": [p_l, p_h], "predict": p}
        # Fill original Venn Abers interval
        xl = np.linspace(-0.5, x[0], 2) if len(x) > 0 else np.linspace(-0.5, 0, 2)
        xh = (
            np.linspace(x[-1], x[-1] + 0.5, 2) if len(x) > 0 else np.linspace(0, 0.5, 2)
        )
        if (
            (p_l < 0.5 and p_h < 0.5)
            or (p_l > 0.5 and p_h > 0.5)
            or "regression" in self._get_explainer().mode
        ):
            color = (
                self.__get_fill_color({"predict": 1}, 0.15)
                if "regression" in self._get_explainer().mode
                else self.__get_fill_color(venn_abers, 0.15)
            )
            ax_main.fill_betweenx(
                x, [p_l] * (num_to_show), [p_h] * (num_to_show), color=color
            )
            # Fill up to the edges
            ax_main.fill_betweenx(xl, [p_l] * (2), [p_h] * (2), color=color)
            ax_main.fill_betweenx(xh, [p_l] * (2), [p_h] * (2), color=color)
            if "regression" in self._get_explainer().mode:
                ax_main.fill_betweenx(x, p, p, color="r", alpha=0.3)
                # Fill up to the edges
                ax_main.fill_betweenx(xl, p, p, color="r", alpha=0.3)
                ax_main.fill_betweenx(xh, p, p, color="r", alpha=0.3)
        else:
            venn_abers["predict"] = p_l
            color = self.__get_fill_color(venn_abers, 0.15)
            ax_main.fill_betweenx(
                x, [p_l] * (num_to_show), [0.5] * (num_to_show), color=color
            )
            # Fill up to the edges
            ax_main.fill_betweenx(xl, [p_l] * (2), [0.5] * (2), color=color)
            ax_main.fill_betweenx(xh, [p_l] * (2), [0.5] * (2), color=color)
            venn_abers["predict"] = p_h
            color = self.__get_fill_color(venn_abers, 0.15)
            ax_main.fill_betweenx(
                x, [0.5] * (num_to_show), [p_h] * (num_to_show), color=color
            )
            # Fill up to the edges
            ax_main.fill_betweenx(xl, [0.5] * (2), [p_h] * (2), color=color)
            ax_main.fill_betweenx(xh, [0.5] * (2), [p_h] * (2), color=color)

        for jx, j in enumerate(features_to_plot):
            p_l = (
                feature_predict["low"][j]
                if feature_predict["low"][j] != -np.inf
                else np.min(self._get_explainer().cal_y)
            )
            p_h = (
                feature_predict["high"][j]
                if feature_predict["high"][j] != np.inf
                else np.max(self._get_explainer().cal_y)
            )
            p = feature_predict["predict"][j]
            xj = np.linspace(x[jx] - 0.2, x[jx] + 0.2, 2)
            venn_abers = {"low_high": [p_l, p_h], "predict": p}
            # Fill each feature impact
            if "regression" in self._get_explainer().mode:
                ax_main.fill_betweenx(xj, p_l, p_h, color="r", alpha=0.40)
                ax_main.fill_betweenx(xj, p, p, color="r")
            elif (p_l < 0.5 and p_h < 0.5) or (p_l > 0.5 and p_h > 0.5):
                ax_main.fill_betweenx(
                    xj, p_l, p_h, color=self.__get_fill_color(venn_abers, 0.99)
                )
            else:
                venn_abers["predict"] = p_l
                ax_main.fill_betweenx(
                    xj, p_l, 0.5, color=self.__get_fill_color(venn_abers, 0.99)
                )
                venn_abers["predict"] = p_h
                ax_main.fill_betweenx(
                    xj, 0.5, p_h, color=self.__get_fill_color(venn_abers, 0.99)
                )

        ax_main.set_yticks(range(num_to_show))
        (
            ax_main.set_yticklabels(labels=[column_names[i] for i in features_to_plot])
            if column_names is not None
            else ax_main.set_yticks(range(num_to_show))
        )  # pylint: disable=expression-not-assigned
        ax_main.set_ylim(-0.5, x[-1] + 0.5 if len(x) > 0 else 0.5)
        ax_main.set_ylabel("Counterfactual rules")
        ax_main_twin = ax_main.twinx()
        ax_main_twin.set_yticks(range(num_to_show))
        ax_main_twin.set_yticklabels([instance[i] for i in features_to_plot])
        ax_main_twin.set_ylim(-0.5, x[-1] + 0.5 if len(x) > 0 else 0.5)
        ax_main_twin.set_ylabel("Instance values")
        if self._is_thresholded():
            # pylint: disable=unsubscriptable-object
            if np.isscalar(self.y_threshold):
                ax_main.set_xlabel(
                    "Probability of target being above "
                    + f"{float(self.y_threshold) :.2f}"
                )
            else:
                ax_main.set_xlabel(
                    "Probability of target being above "
                    + f"{float(self.y_threshold) :.2f}"
                )
            ax_main.set_xlim(0, 1)
            ax_main.set_xticks(np.linspace(0, 1, 11))
        elif "regression" in self._get_explainer().mode:
            ax_main.set_xlabel(
                f"Prediction interval with {self.calibrated_explanations.get_confidence()}% confidence"
            )
            ax_main.set_xlim(
                [
                    np.min(self._get_explainer().cal_y),
                    np.max(self._get_explainer().cal_y),
                ]
            )
        else:
            if self._get_explainer().class_labels is not None:
                if (
                    self._get_explainer()._is_multiclass()
                ):  # pylint: disable=protected-access
                    ax_main.set_xlabel(
                        "Probability for class "
                        + f'\'{self._get_explainer().class_labels[self.prediction["classes"]]}\''
                    )  # pylint: disable=line-too-long
                else:
                    ax_main.set_xlabel(
                        "Probability for class "
                        + f"'{self._get_explainer().class_labels[1]}'"
                    )
            else:
                if (
                    self._get_explainer()._is_multiclass()
                ):  # pylint: disable=protected-access
                    ax_main.set_xlabel(
                        f'Probability for class \'{self.prediction["classes"]}\''
                    )
                else:
                    ax_main.set_xlabel("Probability for the positive class")
            ax_main.set_xlim(0, 1)
            ax_main.set_xticks(np.linspace(0, 1, 11))

        try:
            fig.tight_layout()
        except:  # pylint: disable=bare-except
            pass
        for ext in save_ext:
            fig.savefig(path + title + ext, bbox_inches="tight")
        if show:
            fig.show()

    # pylint: disable=invalid-name
    def __color_brew(self, n):
        color_list = []

        # Initialize saturation & value; calculate chroma & value shift
        s, v = 0.75, 0.9
        c = s * v
        m = v - c

        # for h in np.arange(25, 385, 360. / n).astype(int):
        for h in np.arange(5, 385, 490.0 / n).astype(int):
            # Calculate some intermediate values
            h_bar = h / 60.0
            x = c * (1 - abs((h_bar % 2) - 1))
            # Initialize RGB with same hue & chroma as our color
            rgb = [
                (c, x, 0),
                (x, c, 0),
                (0, c, x),
                (0, x, c),
                (x, 0, c),
                (c, 0, x),
                (c, x, 0),
            ]
            r, g, b = rgb[int(h_bar)]
            # Shift the initial RGB values to match value and store
            rgb = [(int(255 * (r + m))), (int(255 * (g + m))), (int(255 * (b + m)))]
            color_list.append(rgb)
        color_list.reverse()
        return color_list

    def __get_fill_color(
        self, venn_abers, reduction=1
    ):  # pylint: disable=unused-private-member
        colors = self.__color_brew(2)
        winner_class = int(venn_abers["predict"] >= 0.5)
        color = colors[winner_class]

        alpha = (
            venn_abers["predict"] if winner_class == 1 else 1 - venn_abers["predict"]
        )
        alpha = ((alpha - 0.5) / (1 - 0.5)) * (
            1 - 0.25
        ) + 0.25  # normalize values to the range [.25,1]
        if reduction != 1:
            alpha = reduction

        # unpack numpy scalars
        alpha = float(alpha)
        # compute the color as alpha against white
        color = [int(round(alpha * c + (1 - alpha) * 255, 0)) for c in color]
        # Return html color code in #RRGGBB format
        return "#%2x%2x%2x" % tuple(color)  # pylint: disable=consider-using-f-string
