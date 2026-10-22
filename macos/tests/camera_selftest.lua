assert(_VERSION == "Lua 5.1", "Run camera checks with Lua 5.1, as used by Civ V")
dofile(assert(arg[1], "Expected camera module path"))

Keys = { W=87, A=65, S=83, D=68, G=71, VK_UP=38, VK_LEFT=37, VK_DOWN=40, VK_RIGHT=39, VK_ESCAPE=27 }
KeyEvents = { KeyDown=1, KeyUp=2 }
MouseEvents = { LButtonDown=3, RButtonDown=4 }
local checks = 0
local function check(value, message)
    assert(value, message)
    checks = checks + 1
end

local function fixture()
    local state = { calls={}, moving={} }
    UIManager = {
        GetControl=function() return state.control end,
        GetAlt=function() return state.alt end,
        GetShift=function() return state.shift end,
    }
    UI = { IsCityScreenUp=function() return state.city end }
    ContextPtr = {
        IsHidden=function() return state.hidden end,
        SetInputHandler=function(_, handler) state.input=handler end,
        SetShowHideHandler=function(_, handler) state.show=handler end,
    }
    Events = {}
    for _, name in ipairs({"KeyUpEvent", "SerialEventGameMessagePopup", "SerialEventGameMessagePopupShown",
                           "SerialEventEnterCityScreen", "EnteringLeaderViewMode", "GameplaySetActivePlayer"}) do
        local callbacks = {}
        Events[name] = { Add=function(callback) callbacks[#callbacks+1]=callback end,
                         fire=function(...) for _, callback in ipairs(callbacks) do callback(...) end end }
    end
    local arrow = { [Keys.VK_UP]=true, [Keys.VK_LEFT]=true, [Keys.VK_DOWN]=true, [Keys.VK_RIGHT]=true }
    VPMacInstallCamera(function(message, key, data)
        state.calls[#state.calls+1] = {message, key, data}
        if arrow[key] then
            state.moving[key] = message == KeyEvents.KeyDown or nil
            return true
        end
        return "upstream"
    end)
    return state
end

for key, arrow in pairs({[Keys.W]=Keys.VK_UP, [Keys.A]=Keys.VK_LEFT, [Keys.S]=Keys.VK_DOWN, [Keys.D]=Keys.VK_RIGHT}) do
    local s = fixture()
    check(s.input(KeyEvents.KeyDown, key, 99) == true and s.moving[arrow], "WASD must pan in the expected direction")
    check(s.calls[1][3] == 99, "Input data must survive delegation")
    s.input(KeyEvents.KeyDown, key, 99)
    check(#s.calls == 1, "Autorepeat must not restart movement")
    -- The global emergency release may run before the WorldView key-up.
    Events.KeyUpEvent.fire(key)
    check(not s.moving[arrow], "Global release must stop movement even with another screen focused")
    check(s.input(KeyEvents.KeyUp, key, 0) == true and #s.calls == 2, "Owned release must not fall through to a unit command")
end

for _, modifier in ipairs({"control", "shift", "alt"}) do
    local s = fixture()
    s[modifier] = true
    check(s.input(KeyEvents.KeyDown, Keys.S, 1) == "upstream", "Modified shortcuts must reach upstream")
    check(s.input(KeyEvents.KeyUp, Keys.S, 1) == "upstream", "Modified shortcut releases must reach upstream")
    check(not next(s.moving), "Modified shortcuts must not pan")
end

local s = fixture()
s.input(KeyEvents.KeyDown, Keys.W, 0)
s.input(KeyEvents.KeyDown, Keys.D, 0)
check(s.moving[Keys.VK_UP] and s.moving[Keys.VK_RIGHT], "Independent axes must support diagonal movement")
s.input(KeyEvents.KeyUp, Keys.W, 0)
check(not s.moving[Keys.VK_UP] and s.moving[Keys.VK_RIGHT], "Release must stop only its direction")
s.input(KeyEvents.KeyUp, Keys.D, 0)
check(not next(s.moving), "All released keys must stop")

for _, event in ipairs({"SerialEventGameMessagePopup", "SerialEventGameMessagePopupShown", "SerialEventEnterCityScreen",
                        "EnteringLeaderViewMode", "GameplaySetActivePlayer"}) do
    s = fixture()
    s.input(KeyEvents.KeyDown, Keys.W, 0)
    Events[event].fire()
    check(not next(s.moving), "Screen or popup changes must stop camera motion")
    s.input(KeyEvents.KeyDown, Keys.W, 0)
    check(not next(s.moving), "Held-key repeat after a popup must not restart motion")
    Events.KeyUpEvent.fire(Keys.W)
    s.input(KeyEvents.KeyDown, Keys.W, 0)
    check(s.moving[Keys.VK_UP], "A fresh press after release outside WorldView must work")
end

for _, flag in ipairs({"hidden", "city"}) do
    s = fixture()
    s[flag] = true
    check(s.input(KeyEvents.KeyDown, Keys.A, 0) == "upstream" and not next(s.moving), "Non-map screens must retain their input")
end

s = fixture()
s.input(KeyEvents.KeyDown, Keys.W, 0)
s.show(true)
check(not next(s.moving), "Hiding WorldView must stop camera motion")
check(s.input(KeyEvents.KeyDown, Keys.G, 12) == "upstream", "Unrelated keys must reach upstream")
check(s.input(KeyEvents.KeyDown, Keys.VK_LEFT, 0) == true and s.moving[Keys.VK_LEFT], "Arrow controls must remain available")
s.input(KeyEvents.KeyUp, Keys.VK_LEFT, 0)
check(not next(s.moving), "Arrow releases must retain upstream behavior")

s = fixture()
s.input(KeyEvents.KeyDown, Keys.W, 0)
s.control = true
check(s.input(KeyEvents.KeyUp, Keys.W, 0) == true and not next(s.moving), "Modifier changes while holding a key must not leave motion active")
for _, mouse in ipairs({MouseEvents.LButtonDown, MouseEvents.RButtonDown}) do
    s = fixture()
    s.input(KeyEvents.KeyDown, Keys.W, 0)
    check(s.input(mouse, 0, 0) == "upstream" and not next(s.moving), "Mouse clicks must stop custom movement and still reach upstream")
end
print("WASD camera input checks passed: " .. checks)
