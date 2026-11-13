local look = require("../lib/look")

local function model(ctx)
    local provider = ctx.instance.provider
    local state = provider.state.vpn or {}
    local status = state.status or "unknown"
    local error = ctx.instance.state.actionError or state.error or provider.error
    local label = "Checking…"
    local short = "VPN ?"
    local symbol = "lock.shield"
    local color = "secondaryForeground"
    if provider.status == "not_approved" then
        label = "Approve WireGuard’s helper in Settings > Network & Permissions > Programs."
        short = "VPN !"
        symbol = "exclamationmark.shield"
    elseif provider.status == "failed" or provider.status == "exited" or provider.status == "stopped" then
        label = "Helper " .. provider.status .. ". Disable and re-enable its component, or reload the widget."
        short = "VPN !"
        symbol = "exclamationmark.shield"
    elseif error then
        label = error
        short = "VPN !"
        symbol = "exclamationmark.shield"
        color = "#ff9f0a"
    elseif state.busy or status == "connecting" or status == "disconnecting" then
        label = if state.target == "disconnected" or status == "disconnecting" then "Disconnecting…" else "Connecting…"
        short = "VPN …"
        symbol = "arrow.triangle.2.circlepath"
        color = "#ff9f0a"
    elseif status == "connected" then
        label = "Connected"
        short = "VPN ON"
        symbol = "lock.shield.fill"
        color = "#34c759"
    elseif status == "disconnected" then
        label = "Disconnected"
        short = "VPN OFF"
        symbol = "shield.slash"
    end
    local ready = provider.status == "running"
    local busy = state.busy or ctx.instance.state.sending
        or status == "connecting" or status == "disconnecting"
    return {
        label = label, short = short, symbol = symbol, color = color,
        tunnel = state.tunnel or ctx.instance.options.tunnel,
        connected = status == "connected",
        canToggle = ready and not busy and (status == "connected" or status == "disconnected"),
        ready = ready, error = error,
    }
end

local function send(ctx, action)
    if ctx.instance.state.sending then return end
    ctx.instance.state.sending = true
    ctx.instance.state.actionError = nil
    local handle, err = omniwm.provider.send(action, {}, nil, function(result)
        ctx.instance.state.sending = false
        if not result.ok then
            ctx.instance.state.actionError = result.error or "The VPN action failed."
        end
    end)
    if not handle then
        ctx.instance.state.sending = false
        ctx.instance.state.actionError = err or "Could not contact the WireGuard helper."
    end
end

local function toggle(ctx)
    if model(ctx).canToggle then send(ctx, "toggle") end
end

local function item(key, symbol, label, action, enabled)
    return ui.row{ key = key, w = 280, pad = 10, gap = 10, radius = 8,
        opacity = if enabled == false then 0.5 else 1,
        hover = if action then "foreground/0.08" else nil, onClick = action,
        ui.symbol{ name = symbol, size = 14, color = "secondaryForeground" },
        ui.text{ text = label, size = 13, grow = 1, align = "leading" } }
end

return {
    views = {
        bar = function(ctx)
            local m = model(ctx)
            local scale = look.scale(ctx)
            return look.bar(ctx, {
                onClick = toggle, onRightClick = ui.popout,
                help = m.tunnel .. ": " .. m.label .. "\nClick to toggle · Right-click for menu",
                ui.symbol{ name = m.symbol, size = 15 * scale, color = m.color },
                if not ctx.data.bar.style.vertical then
                    ui.text{ text = m.short, size = 11 * scale, weight = "medium" } else nil,
            })
        end,
        panel = function(ctx)
            local m = model(ctx)
            local rows = { w = 308, gap = 4,
                ui.row{ w = 280, gap = 10,
                    ui.symbol{ name = m.symbol, size = 22, color = m.color },
                    ui.column{ gap = 3, center = false,
                        ui.text{ text = "WireGuard", size = 15, weight = "semibold" },
                        ui.text{ text = m.tunnel, size = 12, color = "secondaryForeground", maxWidth = 246 },
                    },
                },
                ui.text{ text = m.label, w = 280, wrap = true, size = 12, color = m.color },
                ui.box{ w = 280, h = 1, fill = "border" },
                item("toggle", if m.connected then "stop.circle" else "play.circle",
                    if m.connected then "Disconnect" else "Connect",
                    if m.canToggle then toggle else nil, m.canToggle),
                item("refresh", "arrow.clockwise", "Refresh status",
                    if m.ready then function(next) send(next, "refresh") end else nil, m.ready),
                item("open", "arrow.up.forward.app", "Open WireGuard", function()
                    omniwm.run("app-open com.wireguard.macos")
                end),
                item("close", "xmark", "Close", ui.popout),
            }
            return look.panel(ctx, rows)
        end,
    },
}
