package com.pdh.core.ports

import com.pdh.core.domain.SyncMutation
import com.pdh.core.domain.UserSession

/**
 * SessionRepository: Hexagonal output port interface.
 * Implemented by database adapters (Room KMP / SQLDelight) and mock stubs.
 */
interface SessionRepository {
    suspend fun getActiveSession(): UserSession?
    suspend fun saveSession(session: UserSession): Result<Unit>
    suspend fun recordMutation(mutation: SyncMutation): Result<Unit>
    suspend fun getPendingMutations(): List<SyncMutation>
    suspend fun clearPendingMutations(mutationIds: List<String>): Result<Unit>
}
