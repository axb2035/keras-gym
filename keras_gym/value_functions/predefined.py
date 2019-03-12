import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import backend as K

from ..losses import masked_mse_loss
from .generic import GenericV, GenericQ


class FeatureInteractionMixin:
    INTERACTION_OPTS = ('elementwise_quadratic', 'full_quadratic')

    def _interaction_layer(self, interaction):
        if isinstance(interaction, keras.layers.Layer):
            return interaction

        if interaction == 'elementwise_quadratic':
            return keras.layers.Lambda(self._elementwise_quadratic_interaction)

        if interaction == 'full_quadratic':
            return keras.layers.Lambda(self._full_quadratic_interaction)

        raise ValueError(
            "unknown interaction, expected a keras.layers.Layer or a specific "
            "string, one of: {}".format(self.INTERACTION_OPTS))

    @staticmethod
    def _elementwise_quadratic_interaction(x):
        """

        This method generates element-wise quadratic interactions, which only
        include linear and quadratic terms. It does *not* include bilinear
        terms or an intercept. Let `b=batch_size` and `n=num_features` for
        conciseness. The input shape is `[b, n]` and the output shape is
        `[b, 2 * n]`.

        """
        x2 = K.concatenate([x, x ** 2])
        return x2

    def _full_quadratic_interaction(self, x):
        """
        This method generates full-quadratic interactions, which include all
        linear, bilinear and quadratic terms. It does *not* include an
        intercept. Let `b=batch_size` and `n=num_features` for conciseness. The
        input shape is `[b, n]` and the output shape is
        `[b, (n + 1) * (n + 2) / 2 - 1]`.

        .. note:: This method requires the `tensorflow` backend.

        """
        ones = K.ones_like(K.expand_dims(x[:, 0], axis=1))
        x = K.concatenate([ones, x])
        x2 = tf.einsum('ij,ik->ijk', x, x)    # full outer product w/ dupes
        x2 = tf.map_fn(self._triu_slice, x2)  # deduped bi-linear interactions
        return x2

    def _triu_slice(self, tensor):
        """ Take upper-triangular slices to avoid duplicated features. """
        n = self.num_features + 1  # needs to exists before first call
        indices = [[i, j] for i in range(n) for j in range(max(1, i), n)]
        return tf.gather_nd(tensor, indices)


class LinearValueFunctionMixin(FeatureInteractionMixin):

    def _optimizer(self, optimizer, **sgd_kwargs):
        if optimizer is None:
            return keras.optimizers.SGD(**sgd_kwargs)

        if isinstance(optimizer, keras.optimizers.Optimizer):
            return optimizer

        raise ValueError(
            "unknown optimizer, expected a keras.optmizers.Optimizer or "
            "None (which sets the default keras.optimizers.SGD optimizer)")

    def _model(self, output_size, interaction, optimizer, **sgd_kwargs):
        model = keras.Sequential()
        if interaction is not None:
            model.add(self._interaction_layer(interaction))
        model.add(keras.layers.Dense(output_size, kernel_initializer='zeros'))
        model.compile(
            loss=masked_mse_loss,
            optimizer=self._optimizer(optimizer, **sgd_kwargs),
        )
        return model


class LinearV(GenericV, LinearValueFunctionMixin):
    """
    A linear function approximator for a state value function :math:`V(s)`
    using a keras model as function approximator.

    Parameters
    ----------
    env : gym environment spec
        This is used to get information about the shape of the observation
        space and action space.

    interaction : str or keras.layers.Layer, optional
        The desired feature interactions that are fed to the linear regression
        model. Available predefined preprocessors can be chosen by passing a
        string, one of the following:

            interaction='full_quadratic'
                This option generates full-quadratic interactions, which
                include all linear, bilinear and quadratic terms. It does *not*
                include an intercept. Let `b=batch_size` and `n=num_features`
                for conciseness. The input shape is `[b, n]` and the output
                shape is `[b, (n + 1) * (n + 2) / 2 - 1]`.

                .. note:: This option requires the `tensorflow` backend.

            interaction='elementwise_quadratic'
                This option generates element-wise quadratic interactions,
                which only include linear and quadratic terms. It does *not*
                include bilinear terms or an intercept. Let `b=batch_size` and
                `n=num_features` for conciseness. The input shape is `[b, n]`
                and the output shape is `[b, 2 * n]`.

        Otherwise, a custom interaction layer can be passed as well. If left
        unspecified (`interaction=None`), the interaction layer is omitted
        altogether.

    optimizer : keras.optimizers.Optimizer, optional
        If left unspecified (`optimizer=None`), the plain vanilla SGD optimizer
        is used, `keras.optimizers.SGD`. See `keras documentation
        <https://keras.io/optimizers/>`_ for more details.

    sgd_kwargs : keyword arguments
        Keyword arguments for `keras.optimizers.SGD`:

            `lr` : float >= 0
                Learning rate.

            `momentum` : float >= 0
                Parameter that accelerates SGD in the relevant direction and
                dampens oscillations.

            `decay` : float >= 0
                Learning rate decay over each update.

            `nesterov` : boolean
                Whether to apply Nesterov momentum.

        See `keras docs <https://keras.io/optimizers/#sgd>`_ for more details.

    """
    def __init__(self, env, interaction=None, optimizer=None, **sgd_kwargs):
        model = self._model(1, interaction, optimizer, **sgd_kwargs)
        GenericV.__init__(self, env, model)


class LinearQ(GenericQ, LinearValueFunctionMixin):
    """
    A linear function approximator for a state value function :math:`Q(s)`
    using a keras model as function approximator.

    Parameters
    ----------
    env : gym environment spec
        This is used to get information about the shape of the observation
        space and action space.

    model_type : {1, 2}, optional

        Specify the model type. This is important when modeling discrete action
        spaces. A type-I model (`model_type=1`) maps
        :math:`(s,a)\\mapsto Q(s,a)`, whereas a type-II model (`model_type=2`)
        maps :math:`s\\mapsto Q(s,.)`.

    state_action_combiner : {'cross', 'concatenate'} or func

        How to combine the feature vectors coming from `s` and `a`.
        Here 'cross' means taking a flat cross product using
        :py:func:`numpy.kron`, which gives a 1d-array of length
        `dim_s * dim_a`. This choice is suitable for simple linear models,
        including the table-lookup type models. In contrast, 'concatenate'
        uses :py:func:`numpy.hstack` to return a 1d array of length
        `dim_s + dim_a`. This option is more suitable for non-linear models.

    interaction : str or keras.layers.Layer, optional
        The desired feature interactions that are fed to the linear regression
        model. Available predefined preprocessors can be chosen by passing a
        string, one of the following:

            interaction='full_quadratic'
                This option generates full-quadratic interactions, which
                include all linear, bilinear and quadratic terms. It does *not*
                include an intercept. Let `b=batch_size` and `n=num_features`
                for conciseness. The input shape is `[b, n]` and the output
                shape is `[b, (n + 1) * (n + 2) / 2 - 1]`.

                .. note:: This option requires the `tensorflow` backend.

            interaction='elementwise_quadratic'
                This option generates element-wise quadratic interactions,
                which only include linear and quadratic terms. It does *not*
                include bilinear terms or an intercept. Let `b=batch_size` and
                `n=num_features` for conciseness. The input shape is `[b, n]`
                and the output shape is `[b, 2 * n]`.

        Otherwise, a custom interaction layer can be passed as well. If left
        unspecified (`interaction=None`), the interaction layer is omitted
        altogether.

    optimizer : keras.optimizers.Optimizer, optional
        If left unspecified (`optimizer=None`), the plain vanilla SGD optimizer
        is used, `keras.optimizers.SGD`. See `keras documentation
        <https://keras.io/optimizers/>`_ for more details.

    sgd_kwargs : keyword arguments
        Keyword arguments for `keras.optimizers.SGD`:

            `lr` : float >= 0
                Learning rate.

            `momentum` : float >= 0
                Parameter that accelerates SGD in the relevant direction and
                dampens oscillations.

            `decay` : float >= 0
                Learning rate decay over each update.

            `nesterov` : boolean
                Whether to apply Nesterov momentum.

        See `keras docs <https://keras.io/optimizers/#sgd>`_ for more details.

    """
    def __init__(self, env, model_type=1, state_action_combiner='cross',
                 interaction=None, optimizer=None, **sgd_kwargs):
        output_size = env.action_space.n if model_type == 2 else 1
        model = self._model(output_size, interaction, optimizer, **sgd_kwargs)
        GenericQ.__init__(self, env, model, model_type, state_action_combiner)
