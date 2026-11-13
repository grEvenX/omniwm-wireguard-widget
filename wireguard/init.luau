-- The bar and Default Focus Ribbon share this root on OmniWM 0.8.0,
-- whose native providers are available only to the configured island root.
local focusRibbon = require("@self/focus-ribbon")

function render(ctx)
    if ctx.data.island then
        return focusRibbon.render(ctx)
    end
    return ui.component{ id = "wireguard-vpn", view = "bar" }
end

function popout(ctx)
    return ui.component{ id = "wireguard-vpn", view = "panel" }
end
