package com.pdh.core.domain

/**
 * SyncStatus: Tracks the offline synchronization state of local entities.
 */
enum class SyncStatus {
    SYNCED,
    DIRTY_INSERT,
    DIRTY_UPDATE,
    DIRTY_DELETE
}

/**
 * UserSession: Core domain entity representing an authenticated user session.
 * Decoupled from UI, database drivers, and network frameworks.
 */
data class UserSession(
    val userId: String,
    val username: String,
    val authToken: String,
    val serverVersion: Long = 1L,
    val syncStatus: SyncStatus = SyncStatus.SYNCED,
    val lastModifiedUtc: Long = System.currentTimeMillis()
)
