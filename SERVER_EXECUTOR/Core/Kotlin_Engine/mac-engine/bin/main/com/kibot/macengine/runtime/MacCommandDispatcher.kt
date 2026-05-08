package com.kibot.macengine.runtime

import com.kibot.core.ControlPlaneGateway
import com.kibot.macengine.config.MacRuntimeConfig
import com.kibot.macengine.state.MacCommand
import com.kibot.macengine.state.MacStateRepository
import com.kibot.shared.models.BotId
import com.kibot.shared.models.BotDesiredState
import com.kibot.shared.models.CommandType
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.put

class MacCommandDispatcher(
    private val repository: MacStateRepository,
    private val controlPlane: ControlPlaneGateway,
    private val config: MacRuntimeConfig,
) {
    suspend fun dispatch(
        command: MacCommand,
        targetBotId: BotId? = null,
    ) {
        val botId = targetBotId ?: config.controlPlane.botId
        repository.applyAndReturn(command)

        when (command) {
            MacCommand.START_BOT -> {
                controlPlane.setDesiredState(botId, BotDesiredState.ON)
                repository.noteStatus("Bot desired state updated to ON for ${botId.value}.")
            }

            MacCommand.STOP_BOT -> {
                controlPlane.setDesiredState(botId, BotDesiredState.OFF)
                repository.noteStatus("Bot desired state updated to OFF for ${botId.value}.")
            }

            MacCommand.REQUEST_TAKEOVER -> {
                val botState = controlPlane.fetchBotState(config.controlPlane.botId)
                val target = botState?.activeDeviceId?.takeIf { it != config.device.deviceId }
                controlPlane.enqueueCommand(
                    botId = config.controlPlane.botId,
                    createdBy = config.device.deviceId,
                    commandType = CommandType.REQUEST_TAKEOVER,
                    targetDeviceId = target,
                    payloadJson = buildJsonObject {
                        put("requester_device_id", config.device.deviceId.value)
                    }.toString(),
                )
                repository.noteStatus("Takeover request sent to active engine.")
            }

            MacCommand.FORCE_SAFE_TAKEOVER -> {
                controlPlane.enqueueCommand(
                    botId = config.controlPlane.botId,
                    createdBy = config.device.deviceId,
                    commandType = CommandType.FORCE_SAFE_TAKEOVER,
                    targetDeviceId = config.device.deviceId,
                )
                repository.noteStatus("Force safe takeover queued for Mac engine.")
            }

            MacCommand.RELEASE_CONTROL -> {
                controlPlane.enqueueCommand(
                    botId = config.controlPlane.botId,
                    createdBy = config.device.deviceId,
                    commandType = CommandType.RELEASE_CONTROL,
                    targetDeviceId = config.device.deviceId,
                )
                repository.noteStatus("Release control queued for Mac engine.")
            }

            MacCommand.SYNC_NOW -> {
                controlPlane.enqueueCommand(
                    botId = botId,
                    createdBy = config.device.deviceId,
                    commandType = CommandType.SYNC_NOW,
                    targetDeviceId = null,
                )
                repository.noteStatus("Sync requested for ${botId.value}.")
            }
            MacCommand.TOGGLE_LIVE_EXECUTION -> {
                controlPlane.enqueueCommand(
                    botId = botId,
                    createdBy = config.device.deviceId,
                    commandType = CommandType.TOGGLE_LIVE_EXECUTION,
                    targetDeviceId = null,
                )
                repository.noteStatus("Toggle live execution requested for ${botId.value}.")
            }
        }
    }
}
