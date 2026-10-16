package com.pdh.core.domain

/**
 * SyncMutation: Append-only journal entry representing a local offline field mutation.
 * Enables 3-way non-overlapping field merges and conflict resolution.
 */
data class SyncMutation(
    val mutationId: String,
    val entityId: String,
    val entityType: String,
    val baseServerVersion: Long,
    val modifiedFieldsJson: String,
    val timestampUtc: Long = System.currentTimeMillis()
)
