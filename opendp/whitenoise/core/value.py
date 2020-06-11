import numpy as np

from .variant_message_map import variant_message_map
from opendp.whitenoise.core import base_pb2, components_pb2, value_pb2


def serialize_privacy_usage(usage):
    """
    Construct a protobuf object representing privacy usage

    :param usage: either a dict {'epsilon': float, 'delta': float} or PrivacyUsage. May also be contained in a list.
    :return: List[PrivacyUsage]
    """

    if not usage:
        return []

    if issubclass(type(usage), value_pb2.PrivacyUsage):
        return [usage]

    # normalize to array
    if issubclass(type(usage), dict):
        usage = [usage]

    serialized = []
    for column in usage:

        if issubclass(type(usage), value_pb2.PrivacyUsage):
            serialized.append(usage)
            continue

        epsilon = column['epsilon']
        delta = column.get('delta', 0)

        if delta is not None:
            serialized.append(value_pb2.PrivacyUsage(
                approximate=value_pb2.PrivacyUsage.DistanceApproximate(
                    epsilon=epsilon,
                    delta=delta
                )
            ))

        else:
            serialized.append(value_pb2.PrivacyUsage(
                approximate=value_pb2.PrivacyUsage.DistancePure(
                    epsilon=epsilon
                )
            ))

    return serialized


def serialize_privacy_definition(analysis):
    return base_pb2.PrivacyDefinition(
        group_size=analysis.group_size,
        neighboring=base_pb2.PrivacyDefinition.Neighboring.Value(analysis.neighboring.upper()),
        strict_parameter_checks=analysis.strict_parameter_checks,
        protect_overflow=analysis.protect_overflow,
        protect_elapsed_time=analysis.protect_elapsed_time,
        protect_memory_utilization=analysis.protect_memory_utilization,
        protect_floating_point=analysis.protect_floating_point
    )


def serialize_index_key(key):
    return value_pb2.IndexKey(**{{
        str: 'str', int: 'i64', bool: 'bool'
    }[type(key)]: key})


def serialize_component(component):
    arguments = {
        name: component_child.component_id
        for name, component_child in component.arguments.items()
        if component_child is not None
    }
    return components_pb2.Component(**{
        'arguments': value_pb2.IndexmapNodeIds(
            keys=map(serialize_index_key, arguments.keys()),
            values=list(arguments.values())
        ),
        'submission': component.submission_id,
        variant_message_map[component.name]:
            getattr(components_pb2, component.name)(**(component.options or {}))
    })


def serialize_analysis(analysis):
    vertices = {}
    for component_id in analysis.components:
        vertices[component_id] = serialize_component(analysis.components[component_id])

    return base_pb2.Analysis(
        computation_graph=base_pb2.ComputationGraph(value=vertices),
        privacy_definition=serialize_privacy_definition(analysis)
    )


def serialize_release(release_values):
    return base_pb2.Release(
        values={
            component_id: base_pb2.ReleaseNode(
                value=serialize_value(
                    release_values[component_id]['value'],
                    release_values[component_id].get("value_format")),
                privacy_usages=release_values[component_id].get("privacy_usages"),
                public=release_values[component_id]['public'])
            for component_id in release_values
        })


def serialize_array1d(array):
    data_type = {
        np.bool: "bool",
        np.int64: "i64",
        np.float64: "f64",
        np.bool_: "bool",
        np.string_: "string",
        np.str_: "string"
    }[array.dtype.type]

    container_type = {
        np.bool: value_pb2.Array1dBool,
        np.int64: value_pb2.Array1dI64,
        np.float64: value_pb2.Array1dF64,
        np.bool_: value_pb2.Array1dBool,
        np.string_: value_pb2.Array1dStr,
        np.str_: value_pb2.Array1dStr
    }[array.dtype.type]

    return value_pb2.Array1d(**{
        data_type: container_type(data=list(array))
    })


def serialize_indexmap(value):
    return base_pb2.Indexmap(
        keys=[serialize_index_key(k) for k in value.keys()],
        values=[serialize_value(v) for v in value.values()]
    )


def serialize_value(value, value_format=None):

    if value_format == 'indexmap' or issubclass(type(value), dict):
        return base_pb2.Value(
            indexmap=serialize_indexmap(value)
        )

    if value_format == 'jagged':
        if not issubclass(type(value), list):
            value = [value]
        if not any(issubclass(type(elem), list) for elem in value):
            value = [value]
        value = [elem if issubclass(type(elem), list) else [elem] for elem in value]

        return base_pb2.Value(jagged=value_pb2.Jagged(
            data=[serialize_array1d(np.array(column)) for column in value],
            data_type=value_pb2.DataType.Value({
                                                   np.bool: "BOOL",
                                                   np.int64: "I64",
                                                   np.float64: "F64",
                                                   np.bool_: "BOOL",
                                                   np.string_: "STRING",
                                                   np.str_: "STRING"
                                               }[np.array(value[0]).dtype.type])
        ))

    if value_format is not None and value_format != 'array':
        raise ValueError('format must be either "array", "jagged", "indexmap" or None')

    array = np.array(value)

    return base_pb2.Value(
        array=value_pb2.Array(
            shape=list(array.shape),
            flattened=serialize_array1d(array.flatten())
        ))


def serialize_filter_level(filter_level):
    return base_pb2.FilterLevel.Value(filter_level.upper())


def parse_privacy_usage(usage: value_pb2.PrivacyUsage):
    """
    Construct a json object representing privacy usage from a proto object

    :param usage: protobuf message
    :return:
    """

    if issubclass(type(usage), dict):
        return usage

    if usage.HasField("approximate"):
        return {"epsilon": usage.approximate.epsilon, "delta": usage.approximate.delta}

    raise ValueError("unsupported privacy variant")


def parse_index_key(value):
    variant = value.WhichOneof("key")
    if not variant:
        raise ValueError("index key may not be empty")

    return getattr(value, variant)


def parse_array1d_null(array):
    data_type = array.WhichOneof("data")
    if not data_type:
        return

    return [v.option if v.HasField("option") else None for v in list(getattr(array, data_type).data)]


def parse_array1d(array):
    data_type = array.WhichOneof("data")
    if data_type:
        return list(getattr(array, data_type).data)


def parse_jagged(value):
    return [parse_array1d(column) for column in value.data]


def parse_array(value):
    data = parse_array1d(value.flattened)
    if data:
        if value.shape:
            return np.array(data).reshape(value.shape)
        return data[0]


def parse_indexmap(value):
    return {parse_index_key(k): parse_value(v) for k, v in zip(value.keys, value.values)}


def parse_value(value):
    if value.HasField("array"):
        return parse_array(value.array)

    if value.HasField("indexmap"):
        return parse_indexmap(value.indexmap)

    if value.HasField("jagged"):
        return parse_jagged(value.jagged)


def parse_release(release):

    def parse_release_node(release_node):
        parsed = {
            "value": parse_value(release_node.value),
            "value_format": release_node.value.WhichOneof("data"),
            "public": release_node.public
        }
        if release_node.privacy_usages:
            parsed['privacy_usages'] = release_node.privacy_usages
        return parsed

    return {
        node_id: parse_release_node(release_node) for node_id, release_node in release.values.items()
    }
