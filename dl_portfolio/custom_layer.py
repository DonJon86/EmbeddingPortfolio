import tensorflow as tf
import numpy as np
from tensorflow.keras.layers import Layer, LSTM, RNN
# from tensorflow.python.keras.layers.recurrent import DropoutRNNCellMixin
from tensorflow.python.keras.layers.recurrent import SimpleRNNCell
from tensorflow.keras import activations
from tensorflow.keras import backend as K
from tensorflow.keras import constraints
from tensorflow.keras import initializers
from tensorflow.keras import regularizers
from tensorflow.keras.layers import InputSpec


# https://keras.io/guides/making_new_layers_and_models_via_subclassing/

class Linear(Layer):
    def __init__(self, units=32):
        super(Linear, self).__init__()
        self.units = units

    def build(self, input_shape):
        self.w = self.add_weight(
            shape=(input_shape[-1], self.units),
            initializer="random_normal",
            trainable=True,
        )
        self.b = self.add_weight(
            shape=(self.units,), initializer="random_normal", trainable=True
        )

    def call(self, inputs):
        return tf.matmul(inputs, self.w) + self.b


class SmoothRNNCell(SimpleRNNCell, Layer):
    def __init__(self, units,
                 alpha,
                 activation='tanh',
                 use_bias=True,
                 kernel_initializer='glorot_uniform',
                 recurrent_initializer='orthogonal',
                 bias_initializer='zeros',
                 kernel_regularizer=None,
                 recurrent_regularizer=None,
                 bias_regularizer=None,
                 kernel_constraint=None,
                 recurrent_constraint=None,
                 bias_constraint=None,
                 dropout=0.,
                 recurrent_dropout=0.,
                 **kwargs):
        super(SmoothRNNCell, self).__init__(units,
                                              activation=activation,
                                              use_bias=use_bias,
                                              kernel_initializer=kernel_initializer,
                                              recurrent_initializer=recurrent_initializer,
                                              bias_initializer=bias_initializer,
                                              kernel_regularizer=kernel_regularizer,
                                              recurrent_regularizer=recurrent_regularizer,
                                              bias_regularizer=bias_regularizer,
                                              kernel_constraint=kernel_constraint,
                                              recurrent_constraint=recurrent_constraint,
                                              bias_constraint=bias_constraint,
                                              dropout=dropout,
                                              recurrent_dropout=recurrent_dropout,
                                              **kwargs)
        assert 0 <= alpha <= 1
        self.alpha = alpha
        self.units = units
        self.activation = activations.get(activation)
        self.use_bias = use_bias

        self.kernel_initializer = initializers.get(kernel_initializer)
        self.recurrent_initializer = initializers.get(recurrent_initializer)
        self.bias_initializer = initializers.get(bias_initializer)

        self.kernel_regularizer = regularizers.get(kernel_regularizer)
        self.recurrent_regularizer = regularizers.get(recurrent_regularizer)
        self.bias_regularizer = regularizers.get(bias_regularizer)

        self.kernel_constraint = constraints.get(kernel_constraint)
        self.recurrent_constraint = constraints.get(recurrent_constraint)
        self.bias_constraint = constraints.get(bias_constraint)

        self.dropout = min(1., max(0., dropout))
        self.recurrent_dropout = min(1., max(0., recurrent_dropout))
        self.state_size = self.units
        self.output_size = self.units

    def build(self, input_shape):
        self.kernel = self.add_weight(
            shape=(input_shape[-1], self.units),
            name='kernel',
            initializer=self.kernel_initializer,
            regularizer=self.kernel_regularizer,
            constraint=self.kernel_constraint)
        self.recurrent_kernel = self.add_weight(
            shape=(self.units, self.units),
            name='recurrent_kernel',
            initializer=self.recurrent_initializer,
            regularizer=self.recurrent_regularizer,
            constraint=self.recurrent_constraint)
        if self.use_bias:
            self.bias = self.add_weight(
                shape=(self.units,),
                name='bias',
                initializer=self.bias_initializer,
                regularizer=self.bias_regularizer,
                constraint=self.bias_constraint)
        else:
            self.bias = None
        self.built = True

    def call(self, inputs, states, training=None):
        prev_output = states[0] if tf.nest.is_nested(states) else states
        dp_mask = self.get_dropout_mask_for_cell(inputs, training)
        rec_dp_mask = self.get_recurrent_dropout_mask_for_cell(
            prev_output, training)

        if dp_mask is not None:
            h = K.dot(inputs * dp_mask, self.kernel)
        else:
            h = K.dot(inputs, self.kernel)
        if self.bias is not None:
            h = K.bias_add(h, self.bias)

        if rec_dp_mask is not None:
            prev_output = prev_output * rec_dp_mask

        output = h + K.dot(prev_output, self.recurrent_kernel)
        if self.activation is not None:
            output = self.activation(output)

        output = self.alpha * output + (1 - self.alpha) * prev_output

        new_state = [output] if tf.nest.is_nested(states) else output
        return output, new_state


class SmoothRNN(RNN):
    def __init__(self,
                 units,
                 alpha,
                 activation='tanh',
                 use_bias=True,
                 kernel_initializer='glorot_uniform',
                 recurrent_initializer='orthogonal',
                 bias_initializer='zeros',
                 kernel_regularizer=None,
                 recurrent_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 kernel_constraint=None,
                 recurrent_constraint=None,
                 bias_constraint=None,
                 dropout=0.,
                 recurrent_dropout=0.,
                 return_sequences=False,
                 return_state=False,
                 go_backwards=False,
                 stateful=False,
                 unroll=False,
                 **kwargs):
        cell_kwargs = {}
        cell = SmoothRNNCell(
            units,
            alpha,
            activation=activation,
            use_bias=use_bias,
            kernel_initializer=kernel_initializer,
            recurrent_initializer=recurrent_initializer,
            bias_initializer=bias_initializer,
            kernel_regularizer=kernel_regularizer,
            recurrent_regularizer=recurrent_regularizer,
            bias_regularizer=bias_regularizer,
            kernel_constraint=kernel_constraint,
            recurrent_constraint=recurrent_constraint,
            bias_constraint=bias_constraint,
            dropout=dropout,
            recurrent_dropout=recurrent_dropout,
            dtype=kwargs.get('dtype'),
            trainable=kwargs.get('trainable', True),
            **cell_kwargs)
        super(SmoothRNN, self).__init__(
            cell,
            return_sequences=return_sequences,
            return_state=return_state,
            go_backwards=go_backwards,
            stateful=stateful,
            unroll=unroll,
            **kwargs)
        self.activity_regularizer = regularizers.get(activity_regularizer)
        self.input_spec = [InputSpec(ndim=3)]

    def call(self, inputs, mask=None, training=None, initial_state=None):
        return super(SmoothRNN, self).call(
            inputs, mask=mask, training=training, initial_state=initial_state)

    @property
    def units(self):
        return self.cell.units

    @property
    def activation(self):
        return self.cell.activation

    @property
    def use_bias(self):
        return self.cell.use_bias

    @property
    def kernel_initializer(self):
        return self.cell.kernel_initializer

    @property
    def recurrent_initializer(self):
        return self.cell.recurrent_initializer

    @property
    def bias_initializer(self):
        return self.cell.bias_initializer

    @property
    def kernel_regularizer(self):
        return self.cell.kernel_regularizer

    @property
    def recurrent_regularizer(self):
        return self.cell.recurrent_regularizer

    @property
    def bias_regularizer(self):
        return self.cell.bias_regularizer

    @property
    def kernel_constraint(self):
        return self.cell.kernel_constraint

    @property
    def recurrent_constraint(self):
        return self.cell.recurrent_constraint

    @property
    def bias_constraint(self):
        return self.cell.bias_constraint

    @property
    def dropout(self):
        return self.cell.dropout

    @property
    def recurrent_dropout(self):
        return self.cell.recurrent_dropout

    def get_config(self):
        config = {
            'units':
                self.units,
            'activation':
                activations.serialize(self.activation),
            'use_bias':
                self.use_bias,
            'kernel_initializer':
                initializers.serialize(self.kernel_initializer),
            'recurrent_initializer':
                initializers.serialize(self.recurrent_initializer),
            'bias_initializer':
                initializers.serialize(self.bias_initializer),
            'kernel_regularizer':
                regularizers.serialize(self.kernel_regularizer),
            'recurrent_regularizer':
                regularizers.serialize(self.recurrent_regularizer),
            'bias_regularizer':
                regularizers.serialize(self.bias_regularizer),
            'activity_regularizer':
                regularizers.serialize(self.activity_regularizer),
            'kernel_constraint':
                constraints.serialize(self.kernel_constraint),
            'recurrent_constraint':
                constraints.serialize(self.recurrent_constraint),
            'bias_constraint':
                constraints.serialize(self.bias_constraint),
            'dropout':
                self.dropout,
            'recurrent_dropout':
                self.recurrent_dropout
        }
        base_config = super(SmoothRNN, self).get_config()
        del base_config['cell']
        return dict(list(base_config.items()) + list(config.items()))

    @classmethod
    def from_config(cls, config):
        if 'implementation' in config:
            config.pop('implementation')
        return cls(**config)


class DynamicSmoothRNNCell(SimpleRNNCell, Layer):
    def __init__(self,
                 units,
                 activation='tanh',
                 smoother_activation='sigmoid',
                 use_bias=True,
                 kernel_initializer='glorot_uniform',
                 recurrent_initializer='orthogonal',
                 bias_initializer='zeros',
                 kernel_regularizer=None,
                 recurrent_regularizer=None,
                 bias_regularizer=None,
                 kernel_constraint=None,
                 recurrent_constraint=None,
                 bias_constraint=None,
                 dropout=0.,
                 recurrent_dropout=0.,
                 **kwargs):
        super(DynamicSmoothRNNCell, self).__init__(units,
                                                   activation=activation,
                                                   use_bias=use_bias,
                                                   kernel_initializer=kernel_initializer,
                                                   recurrent_initializer=recurrent_initializer,
                                                   bias_initializer=bias_initializer,
                                                   kernel_regularizer=kernel_regularizer,
                                                   recurrent_regularizer=recurrent_regularizer,
                                                   bias_regularizer=bias_regularizer,
                                                   kernel_constraint=kernel_constraint,
                                                   recurrent_constraint=recurrent_constraint,
                                                   bias_constraint=bias_constraint,
                                                   dropout=dropout,
                                                   recurrent_dropout=recurrent_dropout,
                                                   **kwargs)
        self.units = units
        self.activation = activations.get(activation)
        self.smoother_activation = activations.get(smoother_activation)
        self.use_bias = use_bias

        self.kernel_initializer = initializers.get(kernel_initializer)
        self.recurrent_initializer = initializers.get(recurrent_initializer)
        self.bias_initializer = initializers.get(bias_initializer)

        self.kernel_regularizer = regularizers.get(kernel_regularizer)
        self.recurrent_regularizer = regularizers.get(recurrent_regularizer)
        self.bias_regularizer = regularizers.get(bias_regularizer)

        self.kernel_constraint = constraints.get(kernel_constraint)
        self.recurrent_constraint = constraints.get(recurrent_constraint)
        self.bias_constraint = constraints.get(bias_constraint)

        self.dropout = min(1., max(0., dropout))
        self.recurrent_dropout = min(1., max(0., recurrent_dropout))

        # self.reset_after = reset_after
        self.state_size = self.units
        self.output_size = self.units

    def build(self, input_shape):
        input_dim = input_shape[-1]
        self.kernel = self.add_weight(
            shape=(input_dim, self.units * 2),
            name='kernel',
            initializer=self.kernel_initializer,
            regularizer=self.kernel_regularizer,
            constraint=self.kernel_constraint)

        self.recurrent_kernel = self.add_weight(
            shape=(self.units, self.units * 2),
            name='recurrent_kernel',
            initializer=self.recurrent_initializer,
            regularizer=self.recurrent_regularizer,
            constraint=self.recurrent_constraint, )

        if self.use_bias:
            bias_shape = (2 * self.units,)
            self.bias = self.add_weight(shape=bias_shape,
                                        name='bias',
                                        initializer=self.bias_initializer,
                                        regularizer=self.bias_regularizer,
                                        constraint=self.bias_constraint)
        else:
            self.bias = None
        self.built = True

    def call(self, inputs, states, training=None):
        h_tm1 = states[0] if tf.nest.is_nested(states) else states  # previous memory

        dp_mask = self.get_dropout_mask_for_cell(inputs, training, count=3)
        rec_dp_mask = self.get_recurrent_dropout_mask_for_cell(
            h_tm1, training, count=3)

        if self.use_bias:
            input_bias, recurrent_bias = self.bias, None

        if 0. < self.dropout < 1.:
            inputs_s = inputs * dp_mask[0]
            inputs_h = inputs * dp_mask[2]
        else:
            inputs_s = inputs
            inputs_h = inputs

        x_s = K.dot(inputs_s, self.kernel[:, :self.units])
        x_h = K.dot(inputs_h, self.kernel[:, self.units:])

        if self.use_bias:
            x_s = K.bias_add(x_s, input_bias[:self.units])
            x_h = K.bias_add(x_h, input_bias[self.units:])

        if 0. < self.recurrent_dropout < 1.:
            h_tm1_s = h_tm1 * rec_dp_mask[0]
            h_tm1_h = h_tm1 * rec_dp_mask[2]
        else:
            h_tm1_s = h_tm1
            h_tm1_h = h_tm1

        recurrent_s = K.dot(h_tm1_s, self.recurrent_kernel[:, :self.units])
        s = self.smoother_activation(x_s + recurrent_s)
        recurrent_h = K.dot(h_tm1_h, self.recurrent_kernel[:, self.units:])
        hh = self.activation(x_h + recurrent_h)

        # previous and candidate state mixed by smoothing operator
        h = s * hh + (1 - s) * h_tm1
        new_state = [h] if tf.nest.is_nested(states) else h
        return h, new_state


class DynamicSmoothRNN(RNN):
    def __init__(self,
                 units,
                 activation='tanh',
                 smoother_activation='sigmoid',
                 use_bias=True,
                 kernel_initializer='glorot_uniform',
                 recurrent_initializer='orthogonal',
                 bias_initializer='zeros',
                 kernel_regularizer=None,
                 recurrent_regularizer=None,
                 bias_regularizer=None,
                 activity_regularizer=None,
                 kernel_constraint=None,
                 recurrent_constraint=None,
                 bias_constraint=None,
                 dropout=0.,
                 recurrent_dropout=0.,
                 return_sequences=False,
                 return_state=False,
                 go_backwards=False,
                 stateful=False,
                 unroll=False,
                 **kwargs):
        cell_kwargs = {}
        cell = DynamicSmoothRNNCell(
            units,
            activation=activation,
            smoother_activation=smoother_activation,
            use_bias=use_bias,
            kernel_initializer=kernel_initializer,
            recurrent_initializer=recurrent_initializer,
            bias_initializer=bias_initializer,
            kernel_regularizer=kernel_regularizer,
            recurrent_regularizer=recurrent_regularizer,
            bias_regularizer=bias_regularizer,
            kernel_constraint=kernel_constraint,
            recurrent_constraint=recurrent_constraint,
            bias_constraint=bias_constraint,
            dropout=dropout,
            recurrent_dropout=recurrent_dropout,
            dtype=kwargs.get('dtype'),
            trainable=kwargs.get('trainable', True),
            **cell_kwargs)
        super(DynamicSmoothRNN, self).__init__(
            cell,
            return_sequences=return_sequences,
            return_state=return_state,
            go_backwards=go_backwards,
            stateful=stateful,
            unroll=unroll,
            **kwargs)
        self.activity_regularizer = regularizers.get(activity_regularizer)
        self.input_spec = [InputSpec(ndim=3)]

    def call(self, inputs, mask=None, training=None, initial_state=None):
        return super(DynamicSmoothRNN, self).call(
            inputs, mask=mask, training=training, initial_state=initial_state)

    @property
    def units(self):
        return self.cell.units

    @property
    def activation(self):
        return self.cell.activation

    @property
    def smoother_activation(self):
        return self.cell.smoother_activation

    @property
    def use_bias(self):
        return self.cell.use_bias

    @property
    def kernel_initializer(self):
        return self.cell.kernel_initializer

    @property
    def recurrent_initializer(self):
        return self.cell.recurrent_initializer

    @property
    def bias_initializer(self):
        return self.cell.bias_initializer

    @property
    def kernel_regularizer(self):
        return self.cell.kernel_regularizer

    @property
    def recurrent_regularizer(self):
        return self.cell.recurrent_regularizer

    @property
    def bias_regularizer(self):
        return self.cell.bias_regularizer

    @property
    def kernel_constraint(self):
        return self.cell.kernel_constraint

    @property
    def recurrent_constraint(self):
        return self.cell.recurrent_constraint

    @property
    def bias_constraint(self):
        return self.cell.bias_constraint

    @property
    def dropout(self):
        return self.cell.dropout

    @property
    def recurrent_dropout(self):
        return self.cell.recurrent_dropout

    def get_config(self):
        config = {
            'units':
                self.units,
            'activation':
                activations.serialize(self.activation),
            'smoother_activation':
                activations.serialize(self.smoother_activation),
            'use_bias':
                self.use_bias,
            'kernel_initializer':
                initializers.serialize(self.kernel_initializer),
            'recurrent_initializer':
                initializers.serialize(self.recurrent_initializer),
            'bias_initializer':
                initializers.serialize(self.bias_initializer),
            'kernel_regularizer':
                regularizers.serialize(self.kernel_regularizer),
            'recurrent_regularizer':
                regularizers.serialize(self.recurrent_regularizer),
            'bias_regularizer':
                regularizers.serialize(self.bias_regularizer),
            'activity_regularizer':
                regularizers.serialize(self.activity_regularizer),
            'kernel_constraint':
                constraints.serialize(self.kernel_constraint),
            'recurrent_constraint':
                constraints.serialize(self.recurrent_constraint),
            'bias_constraint':
                constraints.serialize(self.bias_constraint),
            'dropout':
                self.dropout,
            'recurrent_dropout':
                self.recurrent_dropout
        }
        base_config = super(DynamicSmoothRNN, self).get_config()
        del base_config['cell']
        return dict(list(base_config.items()) + list(config.items()))

    @classmethod
    def from_config(cls, config):
        if 'implementation' in config:
            config.pop('implementation')
        return cls(**config)


if __name__ == "__main__":
    np.random.seed(1)
    x = tf.Variable([[1.]])
    linear_layer = Linear(32)
    # The layer's weights are created dynamically the first time the layer is called
    y = linear_layer(x)
    print(y)

    x = tf.Variable([[[1.]]])
    alphaRNN_layer = SmoothRNNCell(1, alpha=1, kernel_initializer='glorot_uniform',
                                     recurrent_initializer='orthogonal',
                                     activation='linear')
    # The layer's weights are created dynamically the first time the layer is called
    y = alphaRNN_layer(x, x)
    print(y)

    simple_rnncell = SimpleRNNCell(1, kernel_initializer='glorot_uniform', recurrent_initializer='orthogonal',
                                   activation='linear')
    print(simple_rnncell(x, x))

    input_ = tf.keras.layers.Input((1, 1))
    layer = RNN(simple_rnncell)
    output = layer(input_)
    model = tf.keras.models.Model(input_, output)
    print(output)
    print(model.summary())
    print(model(x))

    input_ = tf.keras.layers.Input((1, 1))
    layer_1 = RNN(SmoothRNNCell(1, alpha=1, kernel_initializer='glorot_uniform',
                                     recurrent_initializer='orthogonal',
                                     activation='linear'), return_sequences=True)
    layer_2 = RNN(SmoothRNNCell(1, alpha=1, kernel_initializer='glorot_uniform',
                                     recurrent_initializer='orthogonal',
                                     activation='linear'), return_sequences=False)
    hidden_1 = layer_1(input_)
    output = layer_2(hidden_1)
    model = tf.keras.models.Model(input_, output)
    print(output)
    print(model.summary())
    print(model(x))

    input_ = tf.keras.layers.Input((1, 1))
    layer_1 = SmoothRNN(1, alpha=1, kernel_initializer='glorot_uniform',
                          recurrent_initializer='orthogonal',
                          activation='linear', return_sequences=True)
    layer_2 = SmoothRNN(1, alpha=1, kernel_initializer='glorot_uniform',
                          recurrent_initializer='orthogonal',
                          activation='linear', return_sequences=False)
    hidden_1 = layer_1(input_)
    output = layer_2(hidden_1)
    model = tf.keras.models.Model(input_, output)
    print(output)
    print(model.summary())
    print(model(x))

    x = tf.Variable([[[1.]]])
    dynamic_smoothed_RNN_layer = DynamicSmoothRNNCell(1, kernel_initializer='glorot_uniform',
                                                      recurrent_initializer='orthogonal',
                                                      activation='linear')
    # The layer's weights are created dynamically the first time the layer is called
    y = dynamic_smoothed_RNN_layer(x, x)
    print(y)

    input_ = tf.keras.layers.Input((1, 1))
    layer_1 = RNN(DynamicSmoothRNNCell(1, kernel_initializer='glorot_uniform',
                                       recurrent_initializer='orthogonal',
                                       activation='linear'), return_sequences=True)
    layer_2 = RNN(DynamicSmoothRNNCell(1, kernel_initializer='glorot_uniform',
                                       recurrent_initializer='orthogonal',
                                       activation='linear'), return_sequences=False)
    hidden_1 = layer_1(input_)
    output = layer_2(hidden_1)
    model = tf.keras.models.Model(input_, output)
    print(output)
    print(model.summary())
    print(model(x))

    input_ = tf.keras.layers.Input((1, 1))
    layer_1 = DynamicSmoothRNN(1, return_sequences=True)
    layer_2 = DynamicSmoothRNN(1, return_sequences=False)
    hidden_1 = layer_1(input_)
    output = layer_2(hidden_1)
    model = tf.keras.models.Model(input_, output)
    print(output)
    print(model.summary())
    print(model(x))