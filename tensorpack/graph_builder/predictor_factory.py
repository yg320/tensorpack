#!/usr/bin/env python
# -*- coding: utf-8 -*-
# File: predictor_factory.py

import tensorflow as tf
from ..utils import logger
from ..tfutils.common import get_op_tensor_name, get_tensors_by_names
from ..tfutils.tower import TowerContext
from ..tfutils.collection import freeze_collection
from ..utils.naming import TOWER_FREEZE_KEYS

__all__ = ['PredictorFactory']


class PredictorTowerHandle(object):
    def __init__(self, tower_name, input_desc_names, input_tensors=None):
        self._tower_name = tower_name
        self._input_desc_names = [get_op_tensor_name(k)[1] for k in input_desc_names]
        if input_tensors is not None:
            self._input_names = [get_op_tensor_name(k.name)[1] for k in input_tensors]
        else:
            self._input_names = self._input_desc_names

    def get_tensors(self, names):
        def maybe_inside_tower(name):
            name = get_op_tensor_name(name)[1]
            if name in self._input_names:
                return name
            elif name in self._input_desc_names:
                idx = self._input_desc_names.index(name)
                return self._input_names[idx]
            else:
                # if the name is not a placeholder, use it's name in each tower
                return self._tower_name + '/' + name
        names = list(map(maybe_inside_tower, names))
        tensors = get_tensors_by_names(names)
        return tensors


class PredictorFactory(object):
    """ Make predictors from :class:`ModelDesc`."""

    def __init__(self, model, towers, vs_name=''):
        """
        Args:
            model (ModelDesc):
            towers (list[int]): list of available gpu id
            vs_name (str):
        """
        assert isinstance(towers, list), towers
        self._model = model
        self._towers = towers
        self._vs_name = vs_name

        self._names_built = {}

    def build(self, tower_name, device, input=None):
        logger.info("Building predictor tower '{}' on device {} ...".format(tower_name, device))
        assert tower_name not in self._names_built

        with tf.device(device), \
                TowerContext(tower_name, is_training=False), \
                freeze_collection(TOWER_FREEZE_KEYS):
            if input is None:
                input = self._model.get_reused_placehdrs()
            else:
                input = input.get_input_tensors()
            assert isinstance(input, (list, tuple)), input
            self._model.build_graph(input)

        desc_names = [k.name for k in self._model.get_inputs_desc()]
        self._names_built[tower_name] = PredictorTowerHandle(
            tower_name, desc_names, input)
        return self._names_built[tower_name]

    def has_built(self, tower_name):
        return tower_name in self._names_built

    def get_predictor(self, input_names, output_names, tower):
        """
        Args:
            tower (int): need the kth tower (not the gpu id, but the id in TrainConfig.predict_tower)
        Returns:
            an online predictor (which has to be used under the default session)
        """
        tower_name = 'towerp{}'.format(tower)
        tower = self._towers[tower]
        device = '/gpu:{}'.format(tower) if tower >= 0 else '/cpu:0'
        # use a previously-built tower
        # TODO conflict with inference runner??
        if tower_name not in self._names_built:
            with tf.variable_scope(self._vs_name, reuse=True):
                handle = self.build(tower_name, device)
        else:
            handle = self._names_built[tower_name]

        in_tensors = handle.get_tensors(input_names)
        out_tensors = handle.get_tensors(output_names)
        from ..predict import OnlinePredictor   # noqa TODO
        return OnlinePredictor(in_tensors, out_tensors)
