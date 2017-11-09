# Copyright 2016 The TensorFlow Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Tests for tfdbg module debug_data."""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import os
import shutil
import tempfile

import numpy as np

from tensorflow.core.framework import graph_pb2
from tensorflow.core.framework import tensor_pb2
from tensorflow.python.debug.lib import debug_data
from tensorflow.python.framework import test_util
from tensorflow.python.platform import googletest


class DeviceNamePathConversionTest(test_util.TensorFlowTestCase):

  def testDeviceNameToDevicePath(self):
    self.assertEqual(
        debug_data.METADATA_FILE_PREFIX + debug_data.DEVICE_TAG +
        ",job_ps,replica_1,task_2,cpu_0",
        debug_data.device_name_to_device_path("/job:ps/replica:1/task:2/cpu:0"))

  def testDevicePathToDeviceName(self):
    self.assertEqual(
        "/job:ps/replica:1/task:2/cpu:0",
        debug_data.device_path_to_device_name(
            debug_data.METADATA_FILE_PREFIX + debug_data.DEVICE_TAG +
            ",job_ps,replica_1,task_2,cpu_0"))


class ParseNodeOrTensorNameTest(test_util.TensorFlowTestCase):

  def testParseNodeName(self):
    node_name, slot = debug_data.parse_node_or_tensor_name("namespace1/node_1")

    self.assertEqual("namespace1/node_1", node_name)
    self.assertIsNone(slot)

  def testParseTensorName(self):
    node_name, slot = debug_data.parse_node_or_tensor_name(
        "namespace1/node_2:3")

    self.assertEqual("namespace1/node_2", node_name)
    self.assertEqual(3, slot)


class NodeNameChecksTest(test_util.TensorFlowTestCase):

  def testIsCopyNode(self):
    self.assertTrue(debug_data.is_copy_node("__copy_ns1/ns2/node3_0"))

    self.assertFalse(debug_data.is_copy_node("copy_ns1/ns2/node3_0"))
    self.assertFalse(debug_data.is_copy_node("_copy_ns1/ns2/node3_0"))
    self.assertFalse(debug_data.is_copy_node("_copyns1/ns2/node3_0"))
    self.assertFalse(debug_data.is_copy_node("__dbg_ns1/ns2/node3_0"))

  def testIsDebugNode(self):
    self.assertTrue(
        debug_data.is_debug_node("__dbg_ns1/ns2/node3:0_0_DebugIdentity"))

    self.assertFalse(
        debug_data.is_debug_node("dbg_ns1/ns2/node3:0_0_DebugIdentity"))
    self.assertFalse(
        debug_data.is_debug_node("_dbg_ns1/ns2/node3:0_0_DebugIdentity"))
    self.assertFalse(
        debug_data.is_debug_node("_dbgns1/ns2/node3:0_0_DebugIdentity"))
    self.assertFalse(debug_data.is_debug_node("__copy_ns1/ns2/node3_0"))


class ParseDebugNodeNameTest(test_util.TensorFlowTestCase):

  def testParseDebugNodeName_valid(self):
    debug_node_name_1 = "__dbg_ns_a/ns_b/node_c:1_0_DebugIdentity"
    (watched_node, watched_output_slot, debug_op_index,
     debug_op) = debug_data.parse_debug_node_name(debug_node_name_1)

    self.assertEqual("ns_a/ns_b/node_c", watched_node)
    self.assertEqual(1, watched_output_slot)
    self.assertEqual(0, debug_op_index)
    self.assertEqual("DebugIdentity", debug_op)

  def testParseDebugNodeName_invalidPrefix(self):
    invalid_debug_node_name_1 = "__copy_ns_a/ns_b/node_c:1_0_DebugIdentity"

    with self.assertRaisesRegexp(ValueError, "Invalid prefix"):
      debug_data.parse_debug_node_name(invalid_debug_node_name_1)

  def testParseDebugNodeName_missingDebugOpIndex(self):
    invalid_debug_node_name_1 = "__dbg_node1:0_DebugIdentity"

    with self.assertRaisesRegexp(ValueError, "Invalid debug node name"):
      debug_data.parse_debug_node_name(invalid_debug_node_name_1)

  def testParseDebugNodeName_invalidWatchedTensorName(self):
    invalid_debug_node_name_1 = "__dbg_node1_0_DebugIdentity"

    with self.assertRaisesRegexp(ValueError,
                                 "Invalid tensor name in debug node name"):
      debug_data.parse_debug_node_name(invalid_debug_node_name_1)


class HasNanOrInfTest(test_util.TensorFlowTestCase):

  def setUp(self):
    self._dummy_datum = dummy_datum = debug_data.DebugTensorDatum(
        "/foo", "bar_0_DebugIdentity_42")

  def testNaN(self):
    a = np.array([np.nan, np.nan, 7.0])
    self.assertTrue(debug_data.has_inf_or_nan(self._dummy_datum, a))

  def testInf(self):
    a = np.array([np.inf, np.inf, 7.0])
    self.assertTrue(debug_data.has_inf_or_nan(self._dummy_datum, a))

  def testNanAndInf(self):
    a = np.array([np.inf, np.nan, 7.0])
    self.assertTrue(debug_data.has_inf_or_nan(self._dummy_datum, a))

  def testNoNanOrInf(self):
    a = np.array([0.0, 0.0, 7.0])
    self.assertFalse(debug_data.has_inf_or_nan(self._dummy_datum, a))

  def testEmpty(self):
    a = np.array([])
    self.assertFalse(debug_data.has_inf_or_nan(self._dummy_datum, a))

  def testInconvertibleTensorProto(self):
    self.assertFalse(debug_data.has_inf_or_nan(
        self._dummy_datum,
        debug_data.InconvertibleTensorProto(tensor_pb2.TensorProto(),
                                            initialized=False)))
    self.assertFalse(debug_data.has_inf_or_nan(
        self._dummy_datum,
        debug_data.InconvertibleTensorProto(tensor_pb2.TensorProto(),
                                            initialized=True)))

  def testDTypeComplexWorks(self):
    a = np.array([1j, 3j, 3j, 7j], dtype=np.complex128)
    self.assertFalse(debug_data.has_inf_or_nan(self._dummy_datum, a))

    b = np.array([1j, 3j, 3j, 7j, np.nan], dtype=np.complex128)
    self.assertTrue(debug_data.has_inf_or_nan(self._dummy_datum, b))

  def testDTypeIntegerWorks(self):
    a = np.array([1, 3, 3, 7], dtype=np.int16)
    self.assertFalse(debug_data.has_inf_or_nan(self._dummy_datum, a))

  def testDTypeStringGivesFalse(self):
    """isnan and isinf are not applicable to strings."""

    a = np.array(["s", "p", "a", "m"])
    self.assertFalse(debug_data.has_inf_or_nan(self._dummy_datum, a))

  def testDTypeObjectGivesFalse(self):
    dt = np.dtype([("spam", np.str_, 16), ("eggs", np.float64, (2,))])
    a = np.array([("spam", (8.0, 7.0)), ("eggs", (6.0, 5.0))], dtype=dt)
    self.assertFalse(debug_data.has_inf_or_nan(self._dummy_datum, a))


class DebugTensorDatumTest(test_util.TensorFlowTestCase):

  def testDebugDatum(self):
    dump_root = "/tmp/tfdbg_1"
    debug_dump_rel_path = (
        debug_data.METADATA_FILE_PREFIX + debug_data.DEVICE_TAG +
        ",job_localhost,replica_0,task_0,cpu_0" +
        "/ns1/ns2/node_a_1_2_DebugIdentity_1472563253536385")

    datum = debug_data.DebugTensorDatum(dump_root, debug_dump_rel_path)

    self.assertEqual("DebugIdentity", datum.debug_op)
    self.assertEqual("ns1/ns2/node_a_1", datum.node_name)
    self.assertEqual(2, datum.output_slot)
    self.assertEqual("ns1/ns2/node_a_1:2", datum.tensor_name)
    self.assertEqual(1472563253536385, datum.timestamp)
    self.assertEqual("ns1/ns2/node_a_1:2:DebugIdentity", datum.watch_key)
    self.assertEqual(
        os.path.join(dump_root, debug_dump_rel_path), datum.file_path)
    self.assertEqual(
        "{DebugTensorDatum (/job:localhost/replica:0/task:0/cpu:0) "
        "%s:%d @ %s @ %d}" % (datum.node_name,
                              datum.output_slot,
                              datum.debug_op,
                              datum.timestamp), str(datum))
    self.assertEqual(
        "{DebugTensorDatum (/job:localhost/replica:0/task:0/cpu:0) "
        "%s:%d @ %s @ %d}" % (datum.node_name,
                              datum.output_slot,
                              datum.debug_op,
                              datum.timestamp), repr(datum))

  def testDumpSizeBytesIsNoneForNonexistentFilePath(self):
    dump_root = "/tmp/tfdbg_1"
    debug_dump_rel_path = "ns1/ns2/node_foo_1_2_DebugIdentity_1472563253536385"
    datum = debug_data.DebugTensorDatum(dump_root, debug_dump_rel_path)

    self.assertIsNone(datum.dump_size_bytes)


class DebugDumpDirTest(test_util.TensorFlowTestCase):

  def setUp(self):
    self._dump_root = tempfile.mktemp()
    os.mkdir(self._dump_root)

  def tearDown(self):
    # Tear down temporary dump directory.
    shutil.rmtree(self._dump_root)

  def _makeDataDirWithMultipleDevicesAndDuplicateNodeNames(self):
    cpu_0_dir = os.path.join(
        self._dump_root,
        debug_data.METADATA_FILE_PREFIX + debug_data.DEVICE_TAG +
        ",job_localhost,replica_0,task_0,cpu_0")
    gpu_0_dir = os.path.join(
        self._dump_root,
        debug_data.METADATA_FILE_PREFIX + debug_data.DEVICE_TAG +
        ",job_localhost,replica_0,task_0,gpu_0")
    gpu_1_dir = os.path.join(
        self._dump_root,
        debug_data.METADATA_FILE_PREFIX + debug_data.DEVICE_TAG +
        ",job_localhost,replica_0,task_0,gpu_1")
    os.makedirs(cpu_0_dir)
    os.makedirs(gpu_0_dir)
    os.makedirs(gpu_1_dir)
    open(os.path.join(
        cpu_0_dir, "node_foo_1_2_DebugIdentity_1472563253536386"), "wb")
    open(os.path.join(
        gpu_0_dir, "node_foo_1_2_DebugIdentity_1472563253536385"), "wb")
    open(os.path.join(
        gpu_1_dir, "node_foo_1_2_DebugIdentity_1472563253536387"), "wb")

  def testDebugDumpDir_nonexistentDumpRoot(self):
    with self.assertRaisesRegexp(IOError, "does not exist"):
      debug_data.DebugDumpDir(tempfile.mktemp() + "_foo")

  def testDebugDumpDir_invalidFileNamingPattern(self):
    # File name with too few underscores should lead to an exception.
    device_dir = os.path.join(
        self._dump_root,
        debug_data.METADATA_FILE_PREFIX + debug_data.DEVICE_TAG +
        ",job_localhost,replica_0,task_0,cpu_0")
    os.makedirs(device_dir)
    open(os.path.join(device_dir, "node1_DebugIdentity_1234"), "wb")

    with self.assertRaisesRegexp(ValueError,
                                 "does not conform to the naming pattern"):
      debug_data.DebugDumpDir(self._dump_root)

  def testDebugDumpDir_validDuplicateNodeNamesWithMultipleDevices(self):
    self._makeDataDirWithMultipleDevicesAndDuplicateNodeNames()

    graph_cpu_0 = graph_pb2.GraphDef()
    node = graph_cpu_0.node.add()
    node.name = "node_foo_1"
    node.op = "FooOp"
    node.device = "/job:localhost/replica:0/task:0/cpu:0"
    graph_gpu_0 = graph_pb2.GraphDef()
    node = graph_gpu_0.node.add()
    node.name = "node_foo_1"
    node.op = "FooOp"
    node.device = "/job:localhost/replica:0/task:0/gpu:0"
    graph_gpu_1 = graph_pb2.GraphDef()
    node = graph_gpu_1.node.add()
    node.name = "node_foo_1"
    node.op = "FooOp"
    node.device = "/job:localhost/replica:0/task:0/gpu:1"

    dump_dir = debug_data.DebugDumpDir(
        self._dump_root,
        partition_graphs=[graph_cpu_0, graph_gpu_0, graph_gpu_1])

    self.assertItemsEqual(
        ["/job:localhost/replica:0/task:0/cpu:0",
         "/job:localhost/replica:0/task:0/gpu:0",
         "/job:localhost/replica:0/task:0/gpu:1"], dump_dir.devices())
    self.assertEqual(1472563253536385, dump_dir.t0)
    self.assertEqual(3, dump_dir.size)

    with self.assertRaisesRegexp(
        ValueError, r"Invalid device name: "):
      dump_dir.nodes("/job:localhost/replica:0/task:0/gpu:2")
    self.assertItemsEqual(["node_foo_1", "node_foo_1", "node_foo_1"],
                          dump_dir.nodes())
    self.assertItemsEqual(
        ["node_foo_1"],
        dump_dir.nodes(device_name="/job:localhost/replica:0/task:0/cpu:0"))

  def testDuplicateNodeNamesInGraphDefOfSingleDeviceRaisesException(self):
    self._makeDataDirWithMultipleDevicesAndDuplicateNodeNames()
    graph_cpu_0 = graph_pb2.GraphDef()
    node = graph_cpu_0.node.add()
    node.name = "node_foo_1"
    node.op = "FooOp"
    node.device = "/job:localhost/replica:0/task:0/cpu:0"
    graph_gpu_0 = graph_pb2.GraphDef()
    node = graph_gpu_0.node.add()
    node.name = "node_foo_1"
    node.op = "FooOp"
    node.device = "/job:localhost/replica:0/task:0/gpu:0"
    graph_gpu_1 = graph_pb2.GraphDef()
    node = graph_gpu_1.node.add()
    node.name = "node_foo_1"
    node.op = "FooOp"
    node.device = "/job:localhost/replica:0/task:0/gpu:1"
    node = graph_gpu_1.node.add()  # Here is the duplicate.
    node.name = "node_foo_1"
    node.op = "FooOp"
    node.device = "/job:localhost/replica:0/task:0/gpu:1"

    with self.assertRaisesRegexp(
        ValueError, r"Duplicate node name on device "):
      debug_data.DebugDumpDir(
          self._dump_root,
          partition_graphs=[graph_cpu_0, graph_gpu_0, graph_gpu_1])

  def testDebugDumpDir_emptyDumpDir(self):
    dump_dir = debug_data.DebugDumpDir(self._dump_root)

    self.assertIsNone(dump_dir.t0)
    self.assertEqual([], dump_dir.dumped_tensor_data)


class GetNodeNameAndOutputSlotTest(test_util.TensorFlowTestCase):

  def testParseTensorNameInputWorks(self):
    self.assertEqual("a", debug_data.get_node_name("a:0"))
    self.assertEqual(0, debug_data.get_output_slot("a:0"))

    self.assertEqual("_b", debug_data.get_node_name("_b:1"))
    self.assertEqual(1, debug_data.get_output_slot("_b:1"))

  def testParseNodeNameInputWorks(self):
    self.assertEqual("a", debug_data.get_node_name("a"))
    self.assertEqual(0, debug_data.get_output_slot("a"))


if __name__ == "__main__":
  googletest.main()