-- Map-only WASD camera controls. Runs in the existing WorldView context.
-- Delegate movement to upstream's arrow handlers; leave other input intact.
function VPMacInstallCamera(previous)
    local arrows = { [Keys.W] = Keys.VK_UP, [Keys.A] = Keys.VK_LEFT,
                     [Keys.S] = Keys.VK_DOWN, [Keys.D] = Keys.VK_RIGHT }
    local held, claimed = {}, {}

    local function modified()
        return UIManager:GetControl() or UIManager:GetAlt() or UIManager:GetShift()
    end

    local function release(key)
        if held[key] then
            held[key] = nil
            previous(KeyEvents.KeyUp, arrows[key], 0)
        end
        if claimed[key] then claimed[key] = "released" end
    end

    local function stop()
        for key in pairs(held) do
            previous(KeyEvents.KeyUp, arrows[key], 0)
        end
        held = {}
    end

    Events.KeyUpEvent.Add(release)
    Events.SerialEventGameMessagePopup.Add(stop)
    Events.SerialEventGameMessagePopupShown.Add(stop)
    Events.SerialEventEnterCityScreen.Add(stop)
    Events.EnteringLeaderViewMode.Add(stop)
    Events.GameplaySetActivePlayer.Add(stop)
    ContextPtr:SetShowHideHandler(function(hidden) if hidden then stop() end end)

    ContextPtr:SetInputHandler(function(message, key, data)
        if message == KeyEvents.KeyUp and arrows[key] then
            local consumed = claimed[key] ~= nil
            release(key)
            claimed[key] = nil
            if consumed or not modified() then return true end
        elseif message == KeyEvents.KeyDown and arrows[key] and not modified()
                and not ContextPtr:IsHidden() and not UI.IsCityScreenUp() then
            -- Ignore repeats, including a held key after opening a popup.
            if claimed[key] ~= "held" then
                claimed[key], held[key] = "held", true
                previous(KeyEvents.KeyDown, arrows[key], data)
            end
            return true
        elseif message == KeyEvents.KeyDown or message == MouseEvents.LButtonDown
                or message == MouseEvents.RButtonDown then
            stop()
        end
        return previous(message, key, data)
    end)
end
