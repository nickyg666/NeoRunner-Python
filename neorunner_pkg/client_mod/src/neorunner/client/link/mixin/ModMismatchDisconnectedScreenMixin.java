package neorunner.client.link.mixin;

import java.net.URI;
import net.minecraft.network.chat.ClickEvent;
import net.minecraft.network.chat.Component;
import org.spongepowered.asm.mixin.Final;
import org.spongepowered.asm.mixin.Mixin;
import org.spongepowered.asm.mixin.Shadow;
import org.spongepowered.asm.mixin.injection.At;
import org.spongepowered.asm.mixin.injection.Inject;
import org.spongepowered.asm.mixin.injection.callback.CallbackInfoReturnable;

/**
 * Makes the download link in NeoForge's mod-mismatch disconnect screen
 * clickable.
 *
 * NeoForge renders a mod channel-list mismatch on its own
 * {@code ModMismatchDisconnectedScreen}, not the vanilla DisconnectedScreen.
 * That screen draws the kick reason through a {@code MultiLineLabel} and never
 * routes clicks on it, so the URL shows as plain text. This mixin intercepts a
 * click in the upper (reason) area and opens any OpenUrl in the reason.
 */
@Mixin(targets = "net.neoforged.neoforge.client.gui.ModMismatchDisconnectedScreen")
public abstract class ModMismatchDisconnectedScreenMixin {
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
        // The reason text sits above the mod-list panel and the "Back to menu"/
        // "Open mods folder" buttons at the bottom; only treat upper clicks as
        // link clicks.
        if (mouseY > this.height * 0.7) {
            return;
        }
        URI uri = findOpenUrl(this.reason);
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

    private static URI findOpenUrl(Component component) {
        ClickEvent ce = component.getStyle().getClickEvent();
        if (ce instanceof ClickEvent.OpenUrl openUrl) {
            return openUrl.uri();
        }
        for (Component sibling : component.getSiblings()) {
            URI uri = findOpenUrl(sibling);
            if (uri != null) {
                return uri;
            }
        }
        return null;
    }
}
