#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements.  See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License.  You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

"""
Fuller unit tests for Python MLlib.
"""

import os
import sys
import tempfile
import array as pyarray
from time import time, sleep
from shutil import rmtree

from numpy import (
    array, array_equal, zeros, inf, random, exp, dot, all, mean, abs)
from numpy import sum as array_sum

from py4j.protocol import Py4JJavaError

if sys.version_info[:2] <= (2, 6):
    try:
        import unittest2 as unittest
    except ImportError:
        sys.stderr.write('Please install unittest2 to test with Python 2.6 or earlier')
        sys.exit(1)
else:
    import unittest

from pyspark import SparkContext
from pyspark.mllib.common import _to_java_object_rdd
from pyspark.mllib.clustering import StreamingKMeans, StreamingKMeansModel
from pyspark.mllib.linalg import Vector, SparseVector, DenseVector, VectorUDT, _convert_to_vector,\
    DenseMatrix, SparseMatrix, Vectors, Matrices, MatrixUDT
from pyspark.mllib.classification import StreamingLogisticRegressionWithSGD
from pyspark.mllib.regression import LabeledPoint, StreamingLinearRegressionWithSGD
from pyspark.mllib.random import RandomRDDs
from pyspark.mllib.stat import Statistics
from pyspark.mllib.feature import Word2Vec
from pyspark.mllib.feature import IDF
from pyspark.mllib.feature import StandardScaler, ElementwiseProduct
from pyspark.mllib.util import LinearDataGenerator
from pyspark.mllib.util import MLUtils
from pyspark.serializers import PickleSerializer
from pyspark.streaming import StreamingContext
from pyspark.sql import SQLContext
from pyspark.streaming import StreamingContext

_have_scipy = False
try:
    import scipy.sparse
    _have_scipy = True
except:
    # No SciPy, but that's okay, we'll skip those tests
    pass

ser = PickleSerializer()
sc = SparkContext('local[4]', "MLlib tests")


class MLlibTestCase(unittest.TestCase):
    def setUp(self):
        self.sc = sc


class MLLibStreamingTestCase(unittest.TestCase):
    def setUp(self):
        self.sc = sc
        self.ssc = StreamingContext(self.sc, 1.0)

    def tearDown(self):
        self.ssc.stop(False)

    @staticmethod
    def _ssc_wait(start_time, end_time, sleep_time):
        while time() - start_time < end_time:
            sleep(0.01)


def _squared_distance(a, b):
    if isinstance(a, Vector):
        return a.squared_distance(b)
    else:
        return b.squared_distance(a)


class VectorTests(MLlibTestCase):

    def _test_serialize(self, v):
        self.assertEqual(v, ser.loads(ser.dumps(v)))
        jvec = self.sc._jvm.SerDe.loads(bytearray(ser.dumps(v)))
        nv = ser.loads(bytes(self.sc._jvm.SerDe.dumps(jvec)))
        self.assertEqual(v, nv)
        vs = [v] * 100
        jvecs = self.sc._jvm.SerDe.loads(bytearray(ser.dumps(vs)))
        nvs = ser.loads(bytes(self.sc._jvm.SerDe.dumps(jvecs)))
        self.assertEqual(vs, nvs)

    def test_serialize(self):
        self._test_serialize(DenseVector(range(10)))
        self._test_serialize(DenseVector(array([1., 2., 3., 4.])))
        self._test_serialize(DenseVector(pyarray.array('d', range(10))))
        self._test_serialize(SparseVector(4, {1: 1, 3: 2}))
        self._test_serialize(SparseVector(3, {}))
        self._test_serialize(DenseMatrix(2, 3, range(6)))
        sm1 = SparseMatrix(
            3, 4, [0, 2, 2, 4, 4], [1, 2, 1, 2], [1.0, 2.0, 4.0, 5.0])
        self._test_serialize(sm1)

    def test_dot(self):
        sv = SparseVector(4, {1: 1, 3: 2})
        dv = DenseVector(array([1., 2., 3., 4.]))
        lst = DenseVector([1, 2, 3, 4])
        mat = array([[1., 2., 3., 4.],
                     [1., 2., 3., 4.],
                     [1., 2., 3., 4.],
                     [1., 2., 3., 4.]])
        arr = pyarray.array('d', [0, 1, 2, 3])
        self.assertEquals(10.0, sv.dot(dv))
        self.assertTrue(array_equal(array([3., 6., 9., 12.]), sv.dot(mat)))
        self.assertEquals(30.0, dv.dot(dv))
        self.assertTrue(array_equal(array([10., 20., 30., 40.]), dv.dot(mat)))
        self.assertEquals(30.0, lst.dot(dv))
        self.assertTrue(array_equal(array([10., 20., 30., 40.]), lst.dot(mat)))
        self.assertEquals(7.0, sv.dot(arr))

    def test_squared_distance(self):
        sv = SparseVector(4, {1: 1, 3: 2})
        dv = DenseVector(array([1., 2., 3., 4.]))
        lst = DenseVector([4, 3, 2, 1])
        lst1 = [4, 3, 2, 1]
        arr = pyarray.array('d', [0, 2, 1, 3])
        narr = array([0, 2, 1, 3])
        self.assertEquals(15.0, _squared_distance(sv, dv))
        self.assertEquals(25.0, _squared_distance(sv, lst))
        self.assertEquals(20.0, _squared_distance(dv, lst))
        self.assertEquals(15.0, _squared_distance(dv, sv))
        self.assertEquals(25.0, _squared_distance(lst, sv))
        self.assertEquals(20.0, _squared_distance(lst, dv))
        self.assertEquals(0.0, _squared_distance(sv, sv))
        self.assertEquals(0.0, _squared_distance(dv, dv))
        self.assertEquals(0.0, _squared_distance(lst, lst))
        self.assertEquals(25.0, _squared_distance(sv, lst1))
        self.assertEquals(3.0, _squared_distance(sv, arr))
        self.assertEquals(3.0, _squared_distance(sv, narr))

    def test_conversion(self):
        # numpy arrays should be automatically upcast to float64
        # tests for fix of [SPARK-5089]
        v = array([1, 2, 3, 4], dtype='float64')
        dv = DenseVector(v)
        self.assertTrue(dv.array.dtype == 'float64')
        v = array([1, 2, 3, 4], dtype='float32')
        dv = DenseVector(v)
        self.assertTrue(dv.array.dtype == 'float64')

    def test_sparse_vector_indexing(self):
        sv = SparseVector(4, {1: 1, 3: 2})
        self.assertEquals(sv[0], 0.)
        self.assertEquals(sv[3], 2.)
        self.assertEquals(sv[1], 1.)
        self.assertEquals(sv[2], 0.)
        self.assertEquals(sv[-1], 2)
        self.assertEquals(sv[-2], 0)
        self.assertEquals(sv[-4], 0)
        for ind in [4, -5]:
            self.assertRaises(ValueError, sv.__getitem__, ind)
        for ind in [7.8, '1']:
            self.assertRaises(TypeError, sv.__getitem__, ind)

    def test_matrix_indexing(self):
        mat = DenseMatrix(3, 2, [0, 1, 4, 6, 8, 10])
        expected = [[0, 6], [1, 8], [4, 10]]
        for i in range(3):
            for j in range(2):
                self.assertEquals(mat[i, j], expected[i][j])

    def test_sparse_matrix(self):
        # Test sparse matrix creation.
        sm1 = SparseMatrix(
            3, 4, [0, 2, 2, 4, 4], [1, 2, 1, 2], [1.0, 2.0, 4.0, 5.0])
        self.assertEquals(sm1.numRows, 3)
        self.assertEquals(sm1.numCols, 4)
        self.assertEquals(sm1.colPtrs.tolist(), [0, 2, 2, 4, 4])
        self.assertEquals(sm1.rowIndices.tolist(), [1, 2, 1, 2])
        self.assertEquals(sm1.values.tolist(), [1.0, 2.0, 4.0, 5.0])

        # Test indexing
        expected = [
            [0, 0, 0, 0],
            [1, 0, 4, 0],
            [2, 0, 5, 0]]

        for i in range(3):
            for j in range(4):
                self.assertEquals(expected[i][j], sm1[i, j])
        self.assertTrue(array_equal(sm1.toArray(), expected))

        # Test conversion to dense and sparse.
        smnew = sm1.toDense().toSparse()
        self.assertEquals(sm1.numRows, smnew.numRows)
        self.assertEquals(sm1.numCols, smnew.numCols)
        self.assertTrue(array_equal(sm1.colPtrs, smnew.colPtrs))
        self.assertTrue(array_equal(sm1.rowIndices, smnew.rowIndices))
        self.assertTrue(array_equal(sm1.values, smnew.values))

        sm1t = SparseMatrix(
            3, 4, [0, 2, 3, 5], [0, 1, 2, 0, 2], [3.0, 2.0, 4.0, 9.0, 8.0],
            isTransposed=True)
        self.assertEquals(sm1t.numRows, 3)
        self.assertEquals(sm1t.numCols, 4)
        self.assertEquals(sm1t.colPtrs.tolist(), [0, 2, 3, 5])
        self.assertEquals(sm1t.rowIndices.tolist(), [0, 1, 2, 0, 2])
        self.assertEquals(sm1t.values.tolist(), [3.0, 2.0, 4.0, 9.0, 8.0])

        expected = [
            [3, 2, 0, 0],
            [0, 0, 4, 0],
            [9, 0, 8, 0]]

        for i in range(3):
            for j in range(4):
                self.assertEquals(expected[i][j], sm1t[i, j])
        self.assertTrue(array_equal(sm1t.toArray(), expected))

    def test_dense_matrix_is_transposed(self):
        mat1 = DenseMatrix(3, 2, [0, 4, 1, 6, 3, 9], isTransposed=True)
        mat = DenseMatrix(3, 2, [0, 1, 3, 4, 6, 9])
        self.assertEquals(mat1, mat)

        expected = [[0, 4], [1, 6], [3, 9]]
        for i in range(3):
            for j in range(2):
                self.assertEquals(mat1[i, j], expected[i][j])
        self.assertTrue(array_equal(mat1.toArray(), expected))

        sm = mat1.toSparse()
        self.assertTrue(array_equal(sm.rowIndices, [1, 2, 0, 1, 2]))
        self.assertTrue(array_equal(sm.colPtrs, [0, 2, 5]))
        self.assertTrue(array_equal(sm.values, [1, 3, 4, 6, 9]))

    def test_parse_vector(self):
        a = DenseVector([3, 4, 6, 7])
        self.assertTrue(str(a), '[3.0,4.0,6.0,7.0]')
        self.assertTrue(Vectors.parse(str(a)), a)
        a = SparseVector(4, [0, 2], [3, 4])
        self.assertTrue(str(a), '(4,[0,2],[3.0,4.0])')
        self.assertTrue(Vectors.parse(str(a)), a)
        a = SparseVector(10, [0, 1], [4, 5])
        self.assertTrue(SparseVector.parse(' (10, [0,1 ],[ 4.0,5.0] )'), a)

    def test_norms(self):
        a = DenseVector([0, 2, 3, -1])
        self.assertAlmostEqual(a.norm(2), 3.742, 3)
        self.assertTrue(a.norm(1), 6)
        self.assertTrue(a.norm(inf), 3)
        a = SparseVector(4, [0, 2], [3, -4])
        self.assertAlmostEqual(a.norm(2), 5)
        self.assertTrue(a.norm(1), 7)
        self.assertTrue(a.norm(inf), 4)

        tmp = SparseVector(4, [0, 2], [3, 0])
        self.assertEqual(tmp.numNonzeros(), 1)


class ListTests(MLlibTestCase):

    """
    Test MLlib algorithms on plain lists, to make sure they're passed through
    as NumPy arrays.
    """

    def test_kmeans(self):
        from pyspark.mllib.clustering import KMeans
        data = [
            [0, 1.1],
            [0, 1.2],
            [1.1, 0],
            [1.2, 0],
        ]
        clusters = KMeans.train(self.sc.parallelize(data), 2, initializationMode="k-means||",
                                initializationSteps=7, epsilon=1e-4)
        self.assertEquals(clusters.predict(data[0]), clusters.predict(data[1]))
        self.assertEquals(clusters.predict(data[2]), clusters.predict(data[3]))

    def test_kmeans_deterministic(self):
        from pyspark.mllib.clustering import KMeans
        X = range(0, 100, 10)
        Y = range(0, 100, 10)
        data = [[x, y] for x, y in zip(X, Y)]
        clusters1 = KMeans.train(self.sc.parallelize(data),
                                 3, initializationMode="k-means||",
                                 seed=42, initializationSteps=7, epsilon=1e-4)
        clusters2 = KMeans.train(self.sc.parallelize(data),
                                 3, initializationMode="k-means||",
                                 seed=42, initializationSteps=7, epsilon=1e-4)
        centers1 = clusters1.centers
        centers2 = clusters2.centers
        for c1, c2 in zip(centers1, centers2):
            # TODO: Allow small numeric difference.
            self.assertTrue(array_equal(c1, c2))

    def test_gmm(self):
        from pyspark.mllib.clustering import GaussianMixture
        data = self.sc.parallelize([
            [1, 2],
            [8, 9],
            [-4, -3],
            [-6, -7],
        ])
        clusters = GaussianMixture.train(data, 2, convergenceTol=0.001,
                                         maxIterations=10, seed=56)
        labels = clusters.predict(data).collect()
        self.assertEquals(labels[0], labels[1])
        self.assertEquals(labels[2], labels[3])

    def test_gmm_deterministic(self):
        from pyspark.mllib.clustering import GaussianMixture
        x = range(0, 100, 10)
        y = range(0, 100, 10)
        data = self.sc.parallelize([[a, b] for a, b in zip(x, y)])
        clusters1 = GaussianMixture.train(data, 5, convergenceTol=0.001,
                                          maxIterations=10, seed=63)
        clusters2 = GaussianMixture.train(data, 5, convergenceTol=0.001,
                                          maxIterations=10, seed=63)
        for c1, c2 in zip(clusters1.weights, clusters2.weights):
            self.assertEquals(round(c1, 7), round(c2, 7))

    def test_classification(self):
        from pyspark.mllib.classification import LogisticRegressionWithSGD, SVMWithSGD, NaiveBayes
        from pyspark.mllib.tree import DecisionTree, DecisionTreeModel, RandomForest,\
            RandomForestModel, GradientBoostedTrees, GradientBoostedTreesModel
        data = [
            LabeledPoint(0.0, [1, 0, 0]),
            LabeledPoint(1.0, [0, 1, 1]),
            LabeledPoint(0.0, [2, 0, 0]),
            LabeledPoint(1.0, [0, 2, 1])
        ]
        rdd = self.sc.parallelize(data)
        features = [p.features.tolist() for p in data]

        temp_dir = tempfile.mkdtemp()

        lr_model = LogisticRegressionWithSGD.train(rdd, iterations=10)
        self.assertTrue(lr_model.predict(features[0]) <= 0)
        self.assertTrue(lr_model.predict(features[1]) > 0)
        self.assertTrue(lr_model.predict(features[2]) <= 0)
        self.assertTrue(lr_model.predict(features[3]) > 0)

        svm_model = SVMWithSGD.train(rdd, iterations=10)
        self.assertTrue(svm_model.predict(features[0]) <= 0)
        self.assertTrue(svm_model.predict(features[1]) > 0)
        self.assertTrue(svm_model.predict(features[2]) <= 0)
        self.assertTrue(svm_model.predict(features[3]) > 0)

        nb_model = NaiveBayes.train(rdd)
        self.assertTrue(nb_model.predict(features[0]) <= 0)
        self.assertTrue(nb_model.predict(features[1]) > 0)
        self.assertTrue(nb_model.predict(features[2]) <= 0)
        self.assertTrue(nb_model.predict(features[3]) > 0)

        categoricalFeaturesInfo = {0: 3}  # feature 0 has 3 categories
        dt_model = DecisionTree.trainClassifier(
            rdd, numClasses=2, categoricalFeaturesInfo=categoricalFeaturesInfo, maxBins=4)
        self.assertTrue(dt_model.predict(features[0]) <= 0)
        self.assertTrue(dt_model.predict(features[1]) > 0)
        self.assertTrue(dt_model.predict(features[2]) <= 0)
        self.assertTrue(dt_model.predict(features[3]) > 0)

        dt_model_dir = os.path.join(temp_dir, "dt")
        dt_model.save(self.sc, dt_model_dir)
        same_dt_model = DecisionTreeModel.load(self.sc, dt_model_dir)
        self.assertEqual(same_dt_model.toDebugString(), dt_model.toDebugString())

        rf_model = RandomForest.trainClassifier(
            rdd, numClasses=2, categoricalFeaturesInfo=categoricalFeaturesInfo, numTrees=10,
            maxBins=4, seed=1)
        self.assertTrue(rf_model.predict(features[0]) <= 0)
        self.assertTrue(rf_model.predict(features[1]) > 0)
        self.assertTrue(rf_model.predict(features[2]) <= 0)
        self.assertTrue(rf_model.predict(features[3]) > 0)

        rf_model_dir = os.path.join(temp_dir, "rf")
        rf_model.save(self.sc, rf_model_dir)
        same_rf_model = RandomForestModel.load(self.sc, rf_model_dir)
        self.assertEqual(same_rf_model.toDebugString(), rf_model.toDebugString())

        gbt_model = GradientBoostedTrees.trainClassifier(
            rdd, categoricalFeaturesInfo=categoricalFeaturesInfo, numIterations=4)
        self.assertTrue(gbt_model.predict(features[0]) <= 0)
        self.assertTrue(gbt_model.predict(features[1]) > 0)
        self.assertTrue(gbt_model.predict(features[2]) <= 0)
        self.assertTrue(gbt_model.predict(features[3]) > 0)

        gbt_model_dir = os.path.join(temp_dir, "gbt")
        gbt_model.save(self.sc, gbt_model_dir)
        same_gbt_model = GradientBoostedTreesModel.load(self.sc, gbt_model_dir)
        self.assertEqual(same_gbt_model.toDebugString(), gbt_model.toDebugString())

        try:
            rmtree(temp_dir)
        except OSError:
            pass

    def test_regression(self):
        from pyspark.mllib.regression import LinearRegressionWithSGD, LassoWithSGD, \
            RidgeRegressionWithSGD
        from pyspark.mllib.tree import DecisionTree, RandomForest, GradientBoostedTrees
        data = [
            LabeledPoint(-1.0, [0, -1]),
            LabeledPoint(1.0, [0, 1]),
            LabeledPoint(-1.0, [0, -2]),
            LabeledPoint(1.0, [0, 2])
        ]
        rdd = self.sc.parallelize(data)
        features = [p.features.tolist() for p in data]

        lr_model = LinearRegressionWithSGD.train(rdd, iterations=10)
        self.assertTrue(lr_model.predict(features[0]) <= 0)
        self.assertTrue(lr_model.predict(features[1]) > 0)
        self.assertTrue(lr_model.predict(features[2]) <= 0)
        self.assertTrue(lr_model.predict(features[3]) > 0)

        lasso_model = LassoWithSGD.train(rdd, iterations=10)
        self.assertTrue(lasso_model.predict(features[0]) <= 0)
        self.assertTrue(lasso_model.predict(features[1]) > 0)
        self.assertTrue(lasso_model.predict(features[2]) <= 0)
        self.assertTrue(lasso_model.predict(features[3]) > 0)

        rr_model = RidgeRegressionWithSGD.train(rdd, iterations=10)
        self.assertTrue(rr_model.predict(features[0]) <= 0)
        self.assertTrue(rr_model.predict(features[1]) > 0)
        self.assertTrue(rr_model.predict(features[2]) <= 0)
        self.assertTrue(rr_model.predict(features[3]) > 0)

        categoricalFeaturesInfo = {0: 2}  # feature 0 has 2 categories
        dt_model = DecisionTree.trainRegressor(
            rdd, categoricalFeaturesInfo=categoricalFeaturesInfo, maxBins=4)
        self.assertTrue(dt_model.predict(features[0]) <= 0)
        self.assertTrue(dt_model.predict(features[1]) > 0)
        self.assertTrue(dt_model.predict(features[2]) <= 0)
        self.assertTrue(dt_model.predict(features[3]) > 0)

        rf_model = RandomForest.trainRegressor(
            rdd, categoricalFeaturesInfo=categoricalFeaturesInfo, numTrees=10, maxBins=4, seed=1)
        self.assertTrue(rf_model.predict(features[0]) <= 0)
        self.assertTrue(rf_model.predict(features[1]) > 0)
        self.assertTrue(rf_model.predict(features[2]) <= 0)
        self.assertTrue(rf_model.predict(features[3]) > 0)

        gbt_model = GradientBoostedTrees.trainRegressor(
            rdd, categoricalFeaturesInfo=categoricalFeaturesInfo, numIterations=4)
        self.assertTrue(gbt_model.predict(features[0]) <= 0)
        self.assertTrue(gbt_model.predict(features[1]) > 0)
        self.assertTrue(gbt_model.predict(features[2]) <= 0)
        self.assertTrue(gbt_model.predict(features[3]) > 0)

        try:
            LinearRegressionWithSGD.train(rdd, initialWeights=array([1.0, 1.0]), iterations=10)
            LassoWithSGD.train(rdd, initialWeights=array([1.0, 1.0]), iterations=10)
            RidgeRegressionWithSGD.train(rdd, initialWeights=array([1.0, 1.0]), iterations=10)
        except ValueError:
            self.fail()

        # Verify that maxBins is being passed through
        GradientBoostedTrees.trainRegressor(
            rdd, categoricalFeaturesInfo=categoricalFeaturesInfo, numIterations=4, maxBins=32)
        with self.assertRaises(Exception) as cm:
            GradientBoostedTrees.trainRegressor(
                rdd, categoricalFeaturesInfo=categoricalFeaturesInfo, numIterations=4, maxBins=1)


class StatTests(MLlibTestCase):
    # SPARK-4023
    def test_col_with_different_rdds(self):
        # numpy
        data = RandomRDDs.normalVectorRDD(self.sc, 1000, 10, 10)
        summary = Statistics.colStats(data)
        self.assertEqual(1000, summary.count())
        # array
        data = self.sc.parallelize([range(10)] * 10)
        summary = Statistics.colStats(data)
        self.assertEqual(10, summary.count())
        # array
        data = self.sc.parallelize([pyarray.array("d", range(10))] * 10)
        summary = Statistics.colStats(data)
        self.assertEqual(10, summary.count())

    def test_col_norms(self):
        data = RandomRDDs.normalVectorRDD(self.sc, 1000, 10, 10)
        summary = Statistics.colStats(data)
        self.assertEqual(10, len(summary.normL1()))
        self.assertEqual(10, len(summary.normL2()))

        data2 = self.sc.parallelize(range(10)).map(lambda x: Vectors.dense(x))
        summary2 = Statistics.colStats(data2)
        self.assertEqual(array([45.0]), summary2.normL1())
        import math
        expectedNormL2 = math.sqrt(sum(map(lambda x: x*x, range(10))))
        self.assertTrue(math.fabs(summary2.normL2()[0] - expectedNormL2) < 1e-14)


class VectorUDTTests(MLlibTestCase):

    dv0 = DenseVector([])
    dv1 = DenseVector([1.0, 2.0])
    sv0 = SparseVector(2, [], [])
    sv1 = SparseVector(2, [1], [2.0])
    udt = VectorUDT()

    def test_json_schema(self):
        self.assertEqual(VectorUDT.fromJson(self.udt.jsonValue()), self.udt)

    def test_serialization(self):
        for v in [self.dv0, self.dv1, self.sv0, self.sv1]:
            self.assertEqual(v, self.udt.deserialize(self.udt.serialize(v)))

    def test_infer_schema(self):
        sqlCtx = SQLContext(self.sc)
        rdd = self.sc.parallelize([LabeledPoint(1.0, self.dv1), LabeledPoint(0.0, self.sv1)])
        df = rdd.toDF()
        schema = df.schema
        field = [f for f in schema.fields if f.name == "features"][0]
        self.assertEqual(field.dataType, self.udt)
        vectors = df.map(lambda p: p.features).collect()
        self.assertEqual(len(vectors), 2)
        for v in vectors:
            if isinstance(v, SparseVector):
                self.assertEqual(v, self.sv1)
            elif isinstance(v, DenseVector):
                self.assertEqual(v, self.dv1)
            else:
                raise TypeError("expecting a vector but got %r of type %r" % (v, type(v)))


class MatrixUDTTests(MLlibTestCase):

    dm1 = DenseMatrix(3, 2, [0, 1, 4, 5, 9, 10])
    dm2 = DenseMatrix(3, 2, [0, 1, 4, 5, 9, 10], isTransposed=True)
    sm1 = SparseMatrix(1, 1, [0, 1], [0], [2.0])
    sm2 = SparseMatrix(2, 1, [0, 0, 1], [0], [5.0], isTransposed=True)
    udt = MatrixUDT()

    def test_json_schema(self):
        self.assertEqual(MatrixUDT.fromJson(self.udt.jsonValue()), self.udt)

    def test_serialization(self):
        for m in [self.dm1, self.dm2, self.sm1, self.sm2]:
            self.assertEqual(m, self.udt.deserialize(self.udt.serialize(m)))

    def test_infer_schema(self):
        sqlCtx = SQLContext(self.sc)
        rdd = self.sc.parallelize([("dense", self.dm1), ("sparse", self.sm1)])
        df = rdd.toDF()
        schema = df.schema
        self.assertTrue(schema.fields[1].dataType, self.udt)
        matrices = df.map(lambda x: x._2).collect()
        self.assertEqual(len(matrices), 2)
        for m in matrices:
            if isinstance(m, DenseMatrix):
                self.assertTrue(m, self.dm1)
            elif isinstance(m, SparseMatrix):
                self.assertTrue(m, self.sm1)
            else:
                raise ValueError("Expected a matrix but got type %r" % type(m))


@unittest.skipIf(not _have_scipy, "SciPy not installed")
class SciPyTests(MLlibTestCase):

    """
    Test both vector operations and MLlib algorithms with SciPy sparse matrices,
    if SciPy is available.
    """

    def test_serialize(self):
        from scipy.sparse import lil_matrix
        lil = lil_matrix((4, 1))
        lil[1, 0] = 1
        lil[3, 0] = 2
        sv = SparseVector(4, {1: 1, 3: 2})
        self.assertEquals(sv, _convert_to_vector(lil))
        self.assertEquals(sv, _convert_to_vector(lil.tocsc()))
        self.assertEquals(sv, _convert_to_vector(lil.tocoo()))
        self.assertEquals(sv, _convert_to_vector(lil.tocsr()))
        self.assertEquals(sv, _convert_to_vector(lil.todok()))

        def serialize(l):
            return ser.loads(ser.dumps(_convert_to_vector(l)))
        self.assertEquals(sv, serialize(lil))
        self.assertEquals(sv, serialize(lil.tocsc()))
        self.assertEquals(sv, serialize(lil.tocsr()))
        self.assertEquals(sv, serialize(lil.todok()))

    def test_dot(self):
        from scipy.sparse import lil_matrix
        lil = lil_matrix((4, 1))
        lil[1, 0] = 1
        lil[3, 0] = 2
        dv = DenseVector(array([1., 2., 3., 4.]))
        self.assertEquals(10.0, dv.dot(lil))

    def test_squared_distance(self):
        from scipy.sparse import lil_matrix
        lil = lil_matrix((4, 1))
        lil[1, 0] = 3
        lil[3, 0] = 2
        dv = DenseVector(array([1., 2., 3., 4.]))
        sv = SparseVector(4, {0: 1, 1: 2, 2: 3, 3: 4})
        self.assertEquals(15.0, dv.squared_distance(lil))
        self.assertEquals(15.0, sv.squared_distance(lil))

    def scipy_matrix(self, size, values):
        """Create a column SciPy matrix from a dictionary of values"""
        from scipy.sparse import lil_matrix
        lil = lil_matrix((size, 1))
        for key, value in values.items():
            lil[key, 0] = value
        return lil

    def test_clustering(self):
        from pyspark.mllib.clustering import KMeans
        data = [
            self.scipy_matrix(3, {1: 1.0}),
            self.scipy_matrix(3, {1: 1.1}),
            self.scipy_matrix(3, {2: 1.0}),
            self.scipy_matrix(3, {2: 1.1})
        ]
        clusters = KMeans.train(self.sc.parallelize(data), 2, initializationMode="k-means||")
        self.assertEquals(clusters.predict(data[0]), clusters.predict(data[1]))
        self.assertEquals(clusters.predict(data[2]), clusters.predict(data[3]))

    def test_classification(self):
        from pyspark.mllib.classification import LogisticRegressionWithSGD, SVMWithSGD, NaiveBayes
        from pyspark.mllib.tree import DecisionTree
        data = [
            LabeledPoint(0.0, self.scipy_matrix(2, {0: 1.0})),
            LabeledPoint(1.0, self.scipy_matrix(2, {1: 1.0})),
            LabeledPoint(0.0, self.scipy_matrix(2, {0: 2.0})),
            LabeledPoint(1.0, self.scipy_matrix(2, {1: 2.0}))
        ]
        rdd = self.sc.parallelize(data)
        features = [p.features for p in data]

        lr_model = LogisticRegressionWithSGD.train(rdd)
        self.assertTrue(lr_model.predict(features[0]) <= 0)
        self.assertTrue(lr_model.predict(features[1]) > 0)
        self.assertTrue(lr_model.predict(features[2]) <= 0)
        self.assertTrue(lr_model.predict(features[3]) > 0)

        svm_model = SVMWithSGD.train(rdd)
        self.assertTrue(svm_model.predict(features[0]) <= 0)
        self.assertTrue(svm_model.predict(features[1]) > 0)
        self.assertTrue(svm_model.predict(features[2]) <= 0)
        self.assertTrue(svm_model.predict(features[3]) > 0)

        nb_model = NaiveBayes.train(rdd)
        self.assertTrue(nb_model.predict(features[0]) <= 0)
        self.assertTrue(nb_model.predict(features[1]) > 0)
        self.assertTrue(nb_model.predict(features[2]) <= 0)
        self.assertTrue(nb_model.predict(features[3]) > 0)

        categoricalFeaturesInfo = {0: 3}  # feature 0 has 3 categories
        dt_model = DecisionTree.trainClassifier(rdd, numClasses=2,
                                                categoricalFeaturesInfo=categoricalFeaturesInfo)
        self.assertTrue(dt_model.predict(features[0]) <= 0)
        self.assertTrue(dt_model.predict(features[1]) > 0)
        self.assertTrue(dt_model.predict(features[2]) <= 0)
        self.assertTrue(dt_model.predict(features[3]) > 0)

    def test_regression(self):
        from pyspark.mllib.regression import LinearRegressionWithSGD, LassoWithSGD, \
            RidgeRegressionWithSGD
        from pyspark.mllib.tree import DecisionTree
        data = [
            LabeledPoint(-1.0, self.scipy_matrix(2, {1: -1.0})),
            LabeledPoint(1.0, self.scipy_matrix(2, {1: 1.0})),
            LabeledPoint(-1.0, self.scipy_matrix(2, {1: -2.0})),
            LabeledPoint(1.0, self.scipy_matrix(2, {1: 2.0}))
        ]
        rdd = self.sc.parallelize(data)
        features = [p.features for p in data]

        lr_model = LinearRegressionWithSGD.train(rdd)
        self.assertTrue(lr_model.predict(features[0]) <= 0)
        self.assertTrue(lr_model.predict(features[1]) > 0)
        self.assertTrue(lr_model.predict(features[2]) <= 0)
        self.assertTrue(lr_model.predict(features[3]) > 0)

        lasso_model = LassoWithSGD.train(rdd)
        self.assertTrue(lasso_model.predict(features[0]) <= 0)
        self.assertTrue(lasso_model.predict(features[1]) > 0)
        self.assertTrue(lasso_model.predict(features[2]) <= 0)
        self.assertTrue(lasso_model.predict(features[3]) > 0)

        rr_model = RidgeRegressionWithSGD.train(rdd)
        self.assertTrue(rr_model.predict(features[0]) <= 0)
        self.assertTrue(rr_model.predict(features[1]) > 0)
        self.assertTrue(rr_model.predict(features[2]) <= 0)
        self.assertTrue(rr_model.predict(features[3]) > 0)

        categoricalFeaturesInfo = {0: 2}  # feature 0 has 2 categories
        dt_model = DecisionTree.trainRegressor(rdd, categoricalFeaturesInfo=categoricalFeaturesInfo)
        self.assertTrue(dt_model.predict(features[0]) <= 0)
        self.assertTrue(dt_model.predict(features[1]) > 0)
        self.assertTrue(dt_model.predict(features[2]) <= 0)
        self.assertTrue(dt_model.predict(features[3]) > 0)


class ChiSqTestTests(MLlibTestCase):
    def test_goodness_of_fit(self):
        from numpy import inf

        observed = Vectors.dense([4, 6, 5])
        pearson = Statistics.chiSqTest(observed)

        # Validated against the R command `chisq.test(c(4, 6, 5), p=c(1/3, 1/3, 1/3))`
        self.assertEqual(pearson.statistic, 0.4)
        self.assertEqual(pearson.degreesOfFreedom, 2)
        self.assertAlmostEqual(pearson.pValue, 0.8187, 4)

        # Different expected and observed sum
        observed1 = Vectors.dense([21, 38, 43, 80])
        expected1 = Vectors.dense([3, 5, 7, 20])
        pearson1 = Statistics.chiSqTest(observed1, expected1)

        # Results validated against the R command
        # `chisq.test(c(21, 38, 43, 80), p=c(3/35, 1/7, 1/5, 4/7))`
        self.assertAlmostEqual(pearson1.statistic, 14.1429, 4)
        self.assertEqual(pearson1.degreesOfFreedom, 3)
        self.assertAlmostEqual(pearson1.pValue, 0.002717, 4)

        # Vectors with different sizes
        observed3 = Vectors.dense([1.0, 2.0, 3.0])
        expected3 = Vectors.dense([1.0, 2.0, 3.0, 4.0])
        self.assertRaises(ValueError, Statistics.chiSqTest, observed3, expected3)

        # Negative counts in observed
        neg_obs = Vectors.dense([1.0, 2.0, 3.0, -4.0])
        self.assertRaises(Py4JJavaError, Statistics.chiSqTest, neg_obs, expected1)

        # Count = 0.0 in expected but not observed
        zero_expected = Vectors.dense([1.0, 0.0, 3.0])
        pearson_inf = Statistics.chiSqTest(observed, zero_expected)
        self.assertEqual(pearson_inf.statistic, inf)
        self.assertEqual(pearson_inf.degreesOfFreedom, 2)
        self.assertEqual(pearson_inf.pValue, 0.0)

        # 0.0 in expected and observed simultaneously
        zero_observed = Vectors.dense([2.0, 0.0, 1.0])
        self.assertRaises(Py4JJavaError, Statistics.chiSqTest, zero_observed, zero_expected)

    def test_matrix_independence(self):
        data = [40.0, 24.0, 29.0, 56.0, 32.0, 42.0, 31.0, 10.0, 0.0, 30.0, 15.0, 12.0]
        chi = Statistics.chiSqTest(Matrices.dense(3, 4, data))

        # Results validated against R command
        # `chisq.test(rbind(c(40, 56, 31, 30),c(24, 32, 10, 15), c(29, 42, 0, 12)))`
        self.assertAlmostEqual(chi.statistic, 21.9958, 4)
        self.assertEqual(chi.degreesOfFreedom, 6)
        self.assertAlmostEqual(chi.pValue, 0.001213, 4)

        # Negative counts
        neg_counts = Matrices.dense(2, 2, [4.0, 5.0, 3.0, -3.0])
        self.assertRaises(Py4JJavaError, Statistics.chiSqTest, neg_counts)

        # Row sum = 0.0
        row_zero = Matrices.dense(2, 2, [0.0, 1.0, 0.0, 2.0])
        self.assertRaises(Py4JJavaError, Statistics.chiSqTest, row_zero)

        # Column sum = 0.0
        col_zero = Matrices.dense(2, 2, [0.0, 0.0, 2.0, 2.0])
        self.assertRaises(Py4JJavaError, Statistics.chiSqTest, col_zero)

    def test_chi_sq_pearson(self):
        data = [
            LabeledPoint(0.0, Vectors.dense([0.5, 10.0])),
            LabeledPoint(0.0, Vectors.dense([1.5, 20.0])),
            LabeledPoint(1.0, Vectors.dense([1.5, 30.0])),
            LabeledPoint(0.0, Vectors.dense([3.5, 30.0])),
            LabeledPoint(0.0, Vectors.dense([3.5, 40.0])),
            LabeledPoint(1.0, Vectors.dense([3.5, 40.0]))
        ]

        for numParts in [2, 4, 6, 8]:
            chi = Statistics.chiSqTest(self.sc.parallelize(data, numParts))
            feature1 = chi[0]
            self.assertEqual(feature1.statistic, 0.75)
            self.assertEqual(feature1.degreesOfFreedom, 2)
            self.assertAlmostEqual(feature1.pValue, 0.6873, 4)

            feature2 = chi[1]
            self.assertEqual(feature2.statistic, 1.5)
            self.assertEqual(feature2.degreesOfFreedom, 3)
            self.assertAlmostEqual(feature2.pValue, 0.6823, 4)

    def test_right_number_of_results(self):
        num_cols = 1001
        sparse_data = [
            LabeledPoint(0.0, Vectors.sparse(num_cols, [(100, 2.0)])),
            LabeledPoint(0.1, Vectors.sparse(num_cols, [(200, 1.0)]))
        ]
        chi = Statistics.chiSqTest(self.sc.parallelize(sparse_data))
        self.assertEqual(len(chi), num_cols)
        self.assertIsNotNone(chi[1000])


class SerDeTest(MLlibTestCase):
    def test_to_java_object_rdd(self):  # SPARK-6660
        data = RandomRDDs.uniformRDD(self.sc, 10, 5, seed=0)
        self.assertEqual(_to_java_object_rdd(data).count(), 10)


class FeatureTest(MLlibTestCase):
    def test_idf_model(self):
        data = [
            Vectors.dense([1, 2, 6, 0, 2, 3, 1, 1, 0, 0, 3]),
            Vectors.dense([1, 3, 0, 1, 3, 0, 0, 2, 0, 0, 1]),
            Vectors.dense([1, 4, 1, 0, 0, 4, 9, 0, 1, 2, 0]),
            Vectors.dense([2, 1, 0, 3, 0, 0, 5, 0, 2, 3, 9])
        ]
        model = IDF().fit(self.sc.parallelize(data, 2))
        idf = model.idf()
        self.assertEqual(len(idf), 11)


class Word2VecTests(MLlibTestCase):
    def test_word2vec_setters(self):
        model = Word2Vec() \
            .setVectorSize(2) \
            .setLearningRate(0.01) \
            .setNumPartitions(2) \
            .setNumIterations(10) \
            .setSeed(1024) \
            .setMinCount(3)
        self.assertEquals(model.vectorSize, 2)
        self.assertTrue(model.learningRate < 0.02)
        self.assertEquals(model.numPartitions, 2)
        self.assertEquals(model.numIterations, 10)
        self.assertEquals(model.seed, 1024)
        self.assertEquals(model.minCount, 3)

    def test_word2vec_get_vectors(self):
        data = [
            ["a", "b", "c", "d", "e", "f", "g"],
            ["a", "b", "c", "d", "e", "f"],
            ["a", "b", "c", "d", "e"],
            ["a", "b", "c", "d"],
            ["a", "b", "c"],
            ["a", "b"],
            ["a"]
        ]
        model = Word2Vec().fit(self.sc.parallelize(data))
        self.assertEquals(len(model.getVectors()), 3)


class StandardScalerTests(MLlibTestCase):
    def test_model_setters(self):
        data = [
            [1.0, 2.0, 3.0],
            [2.0, 3.0, 4.0],
            [3.0, 4.0, 5.0]
        ]
        model = StandardScaler().fit(self.sc.parallelize(data))
        self.assertIsNotNone(model.setWithMean(True))
        self.assertIsNotNone(model.setWithStd(True))
        self.assertEqual(model.transform([1.0, 2.0, 3.0]), DenseVector([-1.0, -1.0, -1.0]))

    def test_model_transform(self):
        data = [
            [1.0, 2.0, 3.0],
            [2.0, 3.0, 4.0],
            [3.0, 4.0, 5.0]
        ]
        model = StandardScaler().fit(self.sc.parallelize(data))
        self.assertEqual(model.transform([1.0, 2.0, 3.0]), DenseVector([1.0, 2.0, 3.0]))


class ElementwiseProductTests(MLlibTestCase):
    def test_model_transform(self):
        weight = Vectors.dense([3, 2, 1])

        densevec = Vectors.dense([4, 5, 6])
        sparsevec = Vectors.sparse(3, [0], [1])
        eprod = ElementwiseProduct(weight)
        self.assertEqual(eprod.transform(densevec), DenseVector([12, 10, 6]))
        self.assertEqual(
            eprod.transform(sparsevec), SparseVector(3, [0], [3]))


class StreamingKMeansTest(MLLibStreamingTestCase):
    def test_model_params(self):
        """Test that the model params are set correctly"""
        stkm = StreamingKMeans()
        stkm.setK(5).setDecayFactor(0.0)
        self.assertEquals(stkm._k, 5)
        self.assertEquals(stkm._decayFactor, 0.0)

        # Model not set yet.
        self.assertIsNone(stkm.latestModel())
        self.assertRaises(ValueError, stkm.trainOn, [0.0, 1.0])

        stkm.setInitialCenters(
            centers=[[0.0, 0.0], [1.0, 1.0]], weights=[1.0, 1.0])
        self.assertEquals(
            stkm.latestModel().centers, [[0.0, 0.0], [1.0, 1.0]])
        self.assertEquals(stkm.latestModel().clusterWeights, [1.0, 1.0])

    def test_accuracy_for_single_center(self):
        """Test that parameters obtained are correct for a single center."""
        centers, batches = self.streamingKMeansDataGenerator(
            batches=5, numPoints=5, k=1, d=5, r=0.1, seed=0)
        stkm = StreamingKMeans(1)
        stkm.setInitialCenters([[0., 0., 0., 0., 0.]], [0.])
        input_stream = self.ssc.queueStream(
            [self.sc.parallelize(batch, 1) for batch in batches])
        stkm.trainOn(input_stream)

        t = time()
        self.ssc.start()
        self._ssc_wait(t, 10.0, 0.01)
        self.assertEquals(stkm.latestModel().clusterWeights, [25.0])
        realCenters = array_sum(array(centers), axis=0)
        for i in range(5):
            modelCenters = stkm.latestModel().centers[0][i]
            self.assertAlmostEqual(centers[0][i], modelCenters, 1)
            self.assertAlmostEqual(realCenters[i], modelCenters, 1)

    def streamingKMeansDataGenerator(self, batches, numPoints,
                                     k, d, r, seed, centers=None):
        rng = random.RandomState(seed)

        # Generate centers.
        centers = [rng.randn(d) for i in range(k)]

        return centers, [[Vectors.dense(centers[j % k] + r * rng.randn(d))
                          for j in range(numPoints)]
                         for i in range(batches)]

    def test_trainOn_model(self):
        """Test the model on toy data with four clusters."""
        stkm = StreamingKMeans()
        initCenters = [[1.0, 1.0], [-1.0, 1.0], [-1.0, -1.0], [1.0, -1.0]]
        stkm.setInitialCenters(
            centers=initCenters, weights=[1.0, 1.0, 1.0, 1.0])

        # Create a toy dataset by setting a tiny offest for each point.
        offsets = [[0, 0.1], [0, -0.1], [0.1, 0], [-0.1, 0]]
        batches = []
        for offset in offsets:
            batches.append([[offset[0] + center[0], offset[1] + center[1]]
                            for center in initCenters])

        batches = [self.sc.parallelize(batch, 1) for batch in batches]
        input_stream = self.ssc.queueStream(batches)
        stkm.trainOn(input_stream)
        t = time()
        self.ssc.start()

        # Give enough time to train the model.
        self._ssc_wait(t, 6.0, 0.01)
        finalModel = stkm.latestModel()
        self.assertTrue(all(finalModel.centers == array(initCenters)))
        self.assertEquals(finalModel.clusterWeights, [5.0, 5.0, 5.0, 5.0])

    def test_predictOn_model(self):
        """Test that the model predicts correctly on toy data."""
        stkm = StreamingKMeans()
        stkm._model = StreamingKMeansModel(
            clusterCenters=[[1.0, 1.0], [-1.0, 1.0], [-1.0, -1.0], [1.0, -1.0]],
            clusterWeights=[1.0, 1.0, 1.0, 1.0])

        predict_data = [[[1.5, 1.5]], [[-1.5, 1.5]], [[-1.5, -1.5]], [[1.5, -1.5]]]
        predict_data = [sc.parallelize(batch, 1) for batch in predict_data]
        predict_stream = self.ssc.queueStream(predict_data)
        predict_val = stkm.predictOn(predict_stream)

        result = []

        def update(rdd):
            rdd_collect = rdd.collect()
            if rdd_collect:
                result.append(rdd_collect)

        predict_val.foreachRDD(update)
        t = time()
        self.ssc.start()
        self._ssc_wait(t, 6.0, 0.01)
        self.assertEquals(result, [[0], [1], [2], [3]])

    def test_trainOn_predictOn(self):
        """Test that prediction happens on the updated model."""
        stkm = StreamingKMeans(decayFactor=0.0, k=2)
        stkm.setInitialCenters([[0.0], [1.0]], [1.0, 1.0])

        # Since decay factor is set to zero, once the first batch
        # is passed the clusterCenters are updated to [-0.5, 0.7]
        # which causes 0.2 & 0.3 to be classified as 1, even though the
        # classification based in the initial model would have been 0
        # proving that the model is updated.
        batches = [[[-0.5], [0.6], [0.8]], [[0.2], [-0.1], [0.3]]]
        batches = [sc.parallelize(batch) for batch in batches]
        input_stream = self.ssc.queueStream(batches)
        predict_results = []

        def collect(rdd):
            rdd_collect = rdd.collect()
            if rdd_collect:
                predict_results.append(rdd_collect)

        stkm.trainOn(input_stream)
        predict_stream = stkm.predictOn(input_stream)
        predict_stream.foreachRDD(collect)

        t = time()
        self.ssc.start()
        self._ssc_wait(t, 6.0, 0.01)
        self.assertEqual(predict_results, [[0, 1, 1], [1, 0, 1]])


class LinearDataGeneratorTests(MLlibTestCase):
    def test_dim(self):
        linear_data = LinearDataGenerator.generateLinearInput(
            intercept=0.0, weights=[0.0, 0.0, 0.0],
            xMean=[0.0, 0.0, 0.0], xVariance=[0.33, 0.33, 0.33],
            nPoints=4, seed=0, eps=0.1)
        self.assertEqual(len(linear_data), 4)
        for point in linear_data:
            self.assertEqual(len(point.features), 3)

        linear_data = LinearDataGenerator.generateLinearRDD(
            sc=sc, nexamples=6, nfeatures=2, eps=0.1,
            nParts=2, intercept=0.0).collect()
        self.assertEqual(len(linear_data), 6)
        for point in linear_data:
            self.assertEqual(len(point.features), 2)


class StreamingLogisticRegressionWithSGDTests(MLLibStreamingTestCase):

    @staticmethod
    def generateLogisticInput(offset, scale, nPoints, seed):
        """
        Generate 1 / (1 + exp(-x * scale + offset))

        where,
        x is randomnly distributed and the threshold
        and labels for each sample in x is obtained from a random uniform
        distribution.
        """
        rng = random.RandomState(seed)
        x = rng.randn(nPoints)
        sigmoid = 1. / (1 + exp(-(dot(x, scale) + offset)))
        y_p = rng.rand(nPoints)
        cut_off = y_p <= sigmoid
        y_p[cut_off] = 1.0
        y_p[~cut_off] = 0.0
        return [
            LabeledPoint(y_p[i], Vectors.dense([x[i]]))
            for i in range(nPoints)]

    def test_parameter_accuracy(self):
        """
        Test that the final value of weights is close to the desired value.
        """
        input_batches = [
            self.sc.parallelize(self.generateLogisticInput(0, 1.5, 100, 42 + i))
            for i in range(20)]
        input_stream = self.ssc.queueStream(input_batches)

        slr = StreamingLogisticRegressionWithSGD(
            stepSize=0.2, numIterations=25)
        slr.setInitialWeights([0.0])
        slr.trainOn(input_stream)

        t = time()
        self.ssc.start()
        self._ssc_wait(t, 20.0, 0.01)
        rel = (1.5 - slr.latestModel().weights.array[0]) / 1.5
        self.assertAlmostEqual(rel, 0.1, 1)

    def test_convergence(self):
        """
        Test that weights converge to the required value on toy data.
        """
        input_batches = [
            self.sc.parallelize(self.generateLogisticInput(0, 1.5, 100, 42 + i))
            for i in range(20)]
        input_stream = self.ssc.queueStream(input_batches)
        models = []

        slr = StreamingLogisticRegressionWithSGD(
            stepSize=0.2, numIterations=25)
        slr.setInitialWeights([0.0])
        slr.trainOn(input_stream)
        input_stream.foreachRDD(
            lambda x: models.append(slr.latestModel().weights[0]))

        t = time()
        self.ssc.start()
        self._ssc_wait(t, 15.0, 0.01)
        t_models = array(models)
        diff = t_models[1:] - t_models[:-1]

        # Test that weights improve with a small tolerance,
        self.assertTrue(all(diff >= -0.1))
        self.assertTrue(array_sum(diff > 0) > 1)

    @staticmethod
    def calculate_accuracy_error(true, predicted):
        return sum(abs(array(true) - array(predicted))) / len(true)

    def test_predictions(self):
        """Test predicted values on a toy model."""
        input_batches = []
        for i in range(20):
            batch = self.sc.parallelize(
                self.generateLogisticInput(0, 1.5, 100, 42 + i))
            input_batches.append(batch.map(lambda x: (x.label, x.features)))
        input_stream = self.ssc.queueStream(input_batches)

        slr = StreamingLogisticRegressionWithSGD(
            stepSize=0.2, numIterations=25)
        slr.setInitialWeights([1.5])
        predict_stream = slr.predictOnValues(input_stream)
        true_predicted = []
        predict_stream.foreachRDD(lambda x: true_predicted.append(x.collect()))
        t = time()
        self.ssc.start()
        self._ssc_wait(t, 5.0, 0.01)

        # Test that the accuracy error is no more than 0.4 on each batch.
        for batch in true_predicted:
            true, predicted = zip(*batch)
            self.assertTrue(
                self.calculate_accuracy_error(true, predicted) < 0.4)

    def test_training_and_prediction(self):
        """Test that the model improves on toy data with no. of batches"""
        input_batches = [
            self.sc.parallelize(self.generateLogisticInput(0, 1.5, 100, 42 + i))
            for i in range(20)]
        predict_batches = [
            b.map(lambda lp: (lp.label, lp.features)) for b in input_batches]

        slr = StreamingLogisticRegressionWithSGD(
            stepSize=0.01, numIterations=25)
        slr.setInitialWeights([-0.1])
        errors = []

        def collect_errors(rdd):
            true, predicted = zip(*rdd.collect())
            errors.append(self.calculate_accuracy_error(true, predicted))

        true_predicted = []
        input_stream = self.ssc.queueStream(input_batches)
        predict_stream = self.ssc.queueStream(predict_batches)
        slr.trainOn(input_stream)
        ps = slr.predictOnValues(predict_stream)
        ps.foreachRDD(lambda x: collect_errors(x))

        t = time()
        self.ssc.start()
        self._ssc_wait(t, 20.0, 0.01)

        # Test that the improvement in error is atleast 0.3
        self.assertTrue(errors[1] - errors[-1] > 0.3)


class StreamingLinearRegressionWithTests(MLLibStreamingTestCase):

    def assertArrayAlmostEqual(self, array1, array2, dec):
        for i, j in array1, array2:
            self.assertAlmostEqual(i, j, dec)

    def test_parameter_accuracy(self):
        """Test that coefs are predicted accurately by fitting on toy data."""

        # Test that fitting (10*X1 + 10*X2), (X1, X2) gives coefficients
        # (10, 10)
        slr = StreamingLinearRegressionWithSGD(stepSize=0.2, numIterations=25)
        slr.setInitialWeights([0.0, 0.0])
        xMean = [0.0, 0.0]
        xVariance = [1.0 / 3.0, 1.0 / 3.0]

        # Create ten batches with 100 sample points in each.
        batches = []
        for i in range(10):
            batch = LinearDataGenerator.generateLinearInput(
                0.0, [10.0, 10.0], xMean, xVariance, 100, 42 + i, 0.1)
            batches.append(sc.parallelize(batch))

        input_stream = self.ssc.queueStream(batches)
        t = time()
        slr.trainOn(input_stream)
        self.ssc.start()
        self._ssc_wait(t, 10, 0.01)
        self.assertArrayAlmostEqual(
            slr.latestModel().weights.array, [10., 10.], 1)
        self.assertAlmostEqual(slr.latestModel().intercept, 0.0, 1)

    def test_parameter_convergence(self):
        """Test that the model parameters improve with streaming data."""
        slr = StreamingLinearRegressionWithSGD(stepSize=0.2, numIterations=25)
        slr.setInitialWeights([0.0])

        # Create ten batches with 100 sample points in each.
        batches = []
        for i in range(10):
            batch = LinearDataGenerator.generateLinearInput(
                0.0, [10.0], [0.0], [1.0 / 3.0], 100, 42 + i, 0.1)
            batches.append(sc.parallelize(batch))

        model_weights = []
        input_stream = self.ssc.queueStream(batches)
        input_stream.foreachRDD(
            lambda x: model_weights.append(slr.latestModel().weights[0]))
        t = time()
        slr.trainOn(input_stream)
        self.ssc.start()
        self._ssc_wait(t, 10, 0.01)

        model_weights = array(model_weights)
        diff = model_weights[1:] - model_weights[:-1]
        self.assertTrue(all(diff >= -0.1))

    def test_prediction(self):
        """Test prediction on a model with weights already set."""
        # Create a model with initial Weights equal to coefs
        slr = StreamingLinearRegressionWithSGD(stepSize=0.2, numIterations=25)
        slr.setInitialWeights([10.0, 10.0])

        # Create ten batches with 100 sample points in each.
        batches = []
        for i in range(10):
            batch = LinearDataGenerator.generateLinearInput(
                0.0, [10.0, 10.0], [0.0, 0.0], [1.0 / 3.0, 1.0 / 3.0],
                100, 42 + i, 0.1)
            batches.append(
                sc.parallelize(batch).map(lambda lp: (lp.label, lp.features)))

        input_stream = self.ssc.queueStream(batches)
        t = time()
        output_stream = slr.predictOnValues(input_stream)
        samples = []
        output_stream.foreachRDD(lambda x: samples.append(x.collect()))

        self.ssc.start()
        self._ssc_wait(t, 5, 0.01)

        # Test that mean absolute error on each batch is less than 0.1
        for batch in samples:
            true, predicted = zip(*batch)
            self.assertTrue(mean(abs(array(true) - array(predicted))) < 0.1)

    def test_train_prediction(self):
        """Test that error on test data improves as model is trained."""
        slr = StreamingLinearRegressionWithSGD(stepSize=0.2, numIterations=25)
        slr.setInitialWeights([0.0])

        # Create ten batches with 100 sample points in each.
        batches = []
        for i in range(10):
            batch = LinearDataGenerator.generateLinearInput(
                0.0, [10.0], [0.0], [1.0 / 3.0], 100, 42 + i, 0.1)
            batches.append(sc.parallelize(batch))

        predict_batches = [
            b.map(lambda lp: (lp.label, lp.features)) for b in batches]
        mean_absolute_errors = []

        def func(rdd):
            true, predicted = zip(*rdd.collect())
            mean_absolute_errors.append(mean(abs(true) - abs(predicted)))

        model_weights = []
        input_stream = self.ssc.queueStream(batches)
        output_stream = self.ssc.queueStream(predict_batches)
        t = time()
        slr.trainOn(input_stream)
        output_stream = slr.predictOnValues(output_stream)
        output_stream.foreachRDD(func)
        self.ssc.start()
        self._ssc_wait(t, 10, 0.01)
        self.assertTrue(mean_absolute_errors[1] - mean_absolute_errors[-1] > 2)


class MLUtilsTests(MLlibTestCase):
    def test_append_bias(self):
        data = [2.0, 2.0, 2.0]
        ret = MLUtils.appendBias(data)
        self.assertEqual(ret[3], 1.0)
        self.assertEqual(type(ret), DenseVector)

    def test_append_bias_with_vector(self):
        data = Vectors.dense([2.0, 2.0, 2.0])
        ret = MLUtils.appendBias(data)
        self.assertEqual(ret[3], 1.0)
        self.assertEqual(type(ret), DenseVector)

    def test_append_bias_with_sp_vector(self):
        data = Vectors.sparse(3, {0: 2.0, 2: 2.0})
        expected = Vectors.sparse(4, {0: 2.0, 2: 2.0, 3: 1.0})
        # Returned value must be SparseVector
        ret = MLUtils.appendBias(data)
        self.assertEqual(ret, expected)
        self.assertEqual(type(ret), SparseVector)

    def test_load_vectors(self):
        import shutil
        data = [
            [1.0, 2.0, 3.0],
            [1.0, 2.0, 3.0]
        ]
        temp_dir = tempfile.mkdtemp()
        load_vectors_path = os.path.join(temp_dir, "test_load_vectors")
        try:
            self.sc.parallelize(data).saveAsTextFile(load_vectors_path)
            ret_rdd = MLUtils.loadVectors(self.sc, load_vectors_path)
            ret = ret_rdd.collect()
            self.assertEqual(len(ret), 2)
            self.assertEqual(ret[0], DenseVector([1.0, 2.0, 3.0]))
            self.assertEqual(ret[1], DenseVector([1.0, 2.0, 3.0]))
        except:
            self.fail()
        finally:
            shutil.rmtree(load_vectors_path)


if __name__ == "__main__":
    if not _have_scipy:
        print("NOTE: Skipping SciPy tests as it does not seem to be installed")
    unittest.main()
    if not _have_scipy:
        print("NOTE: SciPy tests were skipped as it does not seem to be installed")
    sc.stop()
