/*
 * Licensed to the Apache Software Foundation (ASF) under one or more
 * contributor license agreements.  See the NOTICE file distributed with
 * this work for additional information regarding copyright ownership.
 * The ASF licenses this file to You under the Apache License, Version 2.0
 * (the "License"); you may not use this file except in compliance with
 * the License.  You may obtain a copy of the License at
 *
 *    http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

package org.apache.spark.sql.execution.joins

import java.io.{ObjectInput, ObjectOutput, Externalizable}
import java.util.{HashMap => JavaHashMap}

import org.apache.spark.sql.catalyst.InternalRow
import org.apache.spark.sql.catalyst.expressions.Projection
import org.apache.spark.sql.execution.SparkSqlSerializer
import org.apache.spark.util.collection.CompactBuffer


/**
 * Interface for a hashed relation by some key. Use [[HashedRelation.apply]] to create a concrete
 * object.
 */
private[joins] sealed trait HashedRelation {
  def get(key: InternalRow): CompactBuffer[InternalRow]

  // This is a helper method to implement Externalizable, and is used by
  // GeneralHashedRelation and UniqueKeyHashedRelation
  protected def writeBytes(out: ObjectOutput, serialized: Array[Byte]): Unit = {
    out.writeInt(serialized.length) // Write the length of serialized bytes first
    out.write(serialized)
  }

  // This is a helper method to implement Externalizable, and is used by
  // GeneralHashedRelation and UniqueKeyHashedRelation
  protected def readBytes(in: ObjectInput): Array[Byte] = {
    val serializedSize = in.readInt() // Read the length of serialized bytes first
    val bytes = new Array[Byte](serializedSize)
    in.readFully(bytes)
    bytes
  }
}


/**
 * A general [[HashedRelation]] backed by a hash map that maps the key into a sequence of values.
 */
private[joins] final class GeneralHashedRelation(
    private var hashTable: JavaHashMap[InternalRow, CompactBuffer[InternalRow]])
  extends HashedRelation with Externalizable {

  def this() = this(null) // Needed for serialization

  override def get(key: InternalRow): CompactBuffer[InternalRow] = hashTable.get(key)

  override def writeExternal(out: ObjectOutput): Unit = {
    writeBytes(out, SparkSqlSerializer.serialize(hashTable))
  }

  override def readExternal(in: ObjectInput): Unit = {
    hashTable = SparkSqlSerializer.deserialize(readBytes(in))
  }
}


/**
 * A specialized [[HashedRelation]] that maps key into a single value. This implementation
 * assumes the key is unique.
 */
private[joins]
final class UniqueKeyHashedRelation(private var hashTable: JavaHashMap[InternalRow, InternalRow])
  extends HashedRelation with Externalizable {

  def this() = this(null) // Needed for serialization

  override def get(key: InternalRow): CompactBuffer[InternalRow] = {
    val v = hashTable.get(key)
    if (v eq null) null else CompactBuffer(v)
  }

  def getValue(key: InternalRow): InternalRow = hashTable.get(key)

  override def writeExternal(out: ObjectOutput): Unit = {
    writeBytes(out, SparkSqlSerializer.serialize(hashTable))
  }

  override def readExternal(in: ObjectInput): Unit = {
    hashTable = SparkSqlSerializer.deserialize(readBytes(in))
  }
}


// TODO(rxin): a version of [[HashedRelation]] backed by arrays for consecutive integer keys.


private[joins] object HashedRelation {

  def apply(
      input: Iterator[InternalRow],
      keyGenerator: Projection,
      sizeEstimate: Int = 64): HashedRelation = {

    // TODO: Use Spark's HashMap implementation.
    val hashTable = new JavaHashMap[InternalRow, CompactBuffer[InternalRow]](sizeEstimate)
    var currentRow: InternalRow = null

    // Whether the join key is unique. If the key is unique, we can convert the underlying
    // hash map into one specialized for this.
    var keyIsUnique = true

    // Create a mapping of buildKeys -> rows
    while (input.hasNext) {
      currentRow = input.next()
      val rowKey = keyGenerator(currentRow)
      if (!rowKey.anyNull) {
        val existingMatchList = hashTable.get(rowKey)
        val matchList = if (existingMatchList == null) {
          val newMatchList = new CompactBuffer[InternalRow]()
          hashTable.put(rowKey, newMatchList)
          newMatchList
        } else {
          keyIsUnique = false
          existingMatchList
        }
        matchList += currentRow.copy()
      }
    }

    if (keyIsUnique) {
      val uniqHashTable = new JavaHashMap[InternalRow, InternalRow](hashTable.size)
      val iter = hashTable.entrySet().iterator()
      while (iter.hasNext) {
        val entry = iter.next()
        uniqHashTable.put(entry.getKey, entry.getValue()(0))
      }
      new UniqueKeyHashedRelation(uniqHashTable)
    } else {
      new GeneralHashedRelation(hashTable)
    }
  }
}
