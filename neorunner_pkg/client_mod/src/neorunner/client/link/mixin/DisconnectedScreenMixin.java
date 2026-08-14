package neorunner.client.link.mixin;

import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * Makes any ClickEvent.OpenUrl inside the disconnect reason clickable.
 *
 * The server sends a download link as an OpenUrl click event on the kick
 * message, but vanilla's DisconnectedScreen never routes component clicks, so
 * the URL shows as plain text. This mixin catches a click on the reason area
 * and opens the URL in the system browser.
 */
@Mixin(targets = "net.minecraft.client.gui.screens.DisconnectedScreen")
public abstract class DisconnectedScreenMixin {
    @Shadow
    @Final
    private Component reason;

    @Shadow
    public int width;

    @Shadow
    public int height;

    @Inject(method = "mouseClicked", at = @At("HEAD"), cancellable = true)
    private void neorunner$openDownloadLink(double mouseX, double mouseY, int button, CallbackInfoReturnable<Boolean> cir) {
        if (button != 0) {
            return;
        }
        // The reason text sits in the upper area; the "Back to ..." buttons are
        // at the bottom. Only treat upper-area clicks as link clicks.
        if (mouseY > this.height * 0.7) {
            return;
        }
        java.net.URI uri = findOpenUrl(this.reason);
        if (uri == null) {
            return;
        }
        try {
            if (java.awt.Desktop.isDesktopSupported()) {
                java.awt.Desktop.getDesktop().browse(uri);
                cir.setReturnValue(true);
            }
        } catch (Exception ignored) {
        }
    }

    private static java.net.URI findOpenUrl(Component component) {
        ClickEvent ce = component.getStyle().getClickEvent();
        if (ce instanceof ClickEvent.OpenUrl openUrl) {
            return openUrl.uri();
        }
        for (Component sibling : component.getSiblings()) {
            java.net.URI uri = findOpenUrl(sibling);
            if (uri != null) {
                return uri;
            }
        }
        return null;
    }
}
