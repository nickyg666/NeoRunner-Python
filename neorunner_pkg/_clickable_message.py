"""Embedded bytecode for the clickable-link disconnect helper.

ClickableMessage.textWithLink(String text, String url) makes the whole
text a clickable component whose click event targets url (the URL itself
is NOT shown as a separate piece of text). Compiled against the Minecraft
net.minecraft.network.chat API (class-file major 69 / Java 25) and embedded
as base64 so the jar patcher can inject it without a JDK on the server.

The Java source is::

    package neorunner_client;

    import java.net.URI;
    import net.minecraft.network.chat.ClickEvent;
    import net.minecraft.network.chat.Component;
    import net.minecraft.network.chat.MutableComponent;
    import net.minecraft.network.chat.Style;

    public final class ClickableMessage {
        private ClickableMessage() {}

        public static MutableComponent textWithLink(String text, String url) {
            MutableComponent result;
            try {
                result = Component.literal(text).withStyle(
                    Style.EMPTY.withClickEvent(new ClickEvent.OpenUrl(URI.create(url))));
            } catch (Exception e) {
                result = Component.literal(text).withStyle(
                    Style.EMPTY.withClickEvent(new ClickEvent.CopyToClipboard(url)));
            }
            return result;
        }
    }
"""

import base64

_CLASS_B64 = (
    "yv66vgAAAEUAPQoAAgADBwAEDAAFAAYBABBqYXZhL2xhbmcvT2JqZWN0AQAGPGluaXQ+AQADKClWCwAIAAkHAAoM"
    "AAsADAEAJG5ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L0NvbXBvbmVudAEAB2xpdGVyYWwBAEEoTGphdmEvbGFu"
    "Zy9TdHJpbmc7KUxuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9NdXRhYmxlQ29tcG9uZW50OwkADgAPBwAQDAAR"
    "ABIBACBuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9TdHlsZQEABUVNUFRZAQAiTG5ldC9taW5lY3JhZnQvbmV0"
    "d29yay9jaGF0L1N0eWxlOwcAFAEALW5ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L0NsaWNrRXZlbnQkT3BlblVy"
    "bAoAFgAXBwAYDAAZABoBAAxqYXZhL25ldC9VUkkBAAZjcmVhdGUBACIoTGphdmEvbGFuZy9TdHJpbmc7KUxqYXZh"
    "L25ldC9VUkk7CgATABwMAAUAHQEAEShMamF2YS9uZXQvVVJJOylWCgAOAB8MACAAIQEADndpdGhDbGlja0V2ZW50"
    "AQBLKExuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9DbGlja0V2ZW50OylMbmV0L21pbmVjcmFmdC9uZXR3b3Jr"
    "L2NoYXQvU3R5bGU7CgAjACQHACUMACYAJwEAK25ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L011dGFibGVDb21w"
    "b25lbnQBAAl3aXRoU3R5bGUBAFEoTG5ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L1N0eWxlOylMbmV0L21pbmVj"
    "cmFmdC9uZXR3b3JrL2NoYXQvTXV0YWJsZUNvbXBvbmVudDsHACkBABNqYXZhL2xhbmcvRXhjZXB0aW9uBwArAQA1"
    "bmV0L21pbmVjcmFmdC9uZXR3b3JrL2NoYXQvQ2xpY2tFdmVudCRDb3B5VG9DbGlwYm9hcmQKACoALQwABQAuAQAV"
    "KExqYXZhL2xhbmcvU3RyaW5nOylWBwAwAQAhbmVvcnVubmVyX2NsaWVudC9DbGlja2FibGVNZXNzYWdlAQAEQ29k"
    "ZQEAD0xpbmVOdW1iZXJUYWJsZQEADHRleHRXaXRoTGluawEAUyhMamF2YS9sYW5nL1N0cmluZztMamF2YS9sYW5n"
    "L1N0cmluZzspTG5ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L011dGFibGVDb21wb25lbnQ7AQANU3RhY2tNYXBU"
    "YWJsZQEAClNvdXJjZUZpbGUBABVDbGlja2FibGVNZXNzYWdlLmphdmEBAAxJbm5lckNsYXNzZXMHADoBACVuZXQv"
    "bWluZWNyYWZ0L25ldHdvcmsvY2hhdC9DbGlja0V2ZW50AQAHT3BlblVybAEAD0NvcHlUb0NsaXBib2FyZAAxAC8A"
    "AgAAAAAAAgACAAUABgABADEAAAAdAAEAAQAAAAUqtwABsQAAAAEAMgAAAAYAAQAAAAoACQAzADQAAQAxAAAAdwAF"
    "AAQAAAA1KrgAB7IADbsAE1kruAAVtwAbtgAetgAiTacAGk4quAAHsgANuwAqWSu3ACy2AB62ACJNLLAAAQAAABkA"
    "HAAoAAIAMgAAABYABQAAAA8AGQASABwAEAAdABEAMwATADUAAAAMAAJcBwAo/AAWBwAjAAIANgAAAAIANwA4AAAA"
    "EgACABMAOQA7ABkAKgA5ADwAGQ=="
)

CLASS_NAME = "neorunner_client/ClickableMessage.class"


def clickable_message_class() -> bytes:
    """Return the compiled neorunner_client.ClickableMessage class bytes."""
    return base64.b64decode(_CLASS_B64)


# A second copy compiled under a different package (neorunner_neoforge) so the
# universal jar (the neoforge JPMS module) can host its own helper class
# without a cross-module reference to the minecraft module's copy. Same body.
_CLASS_B64_NEOFORGE = (
    "yv66vgAAAEUAPQoAAgADBwAEDAAFAAYBABBqYXZhL2xhbmcvT2JqZWN0AQAGPGluaXQ+AQADKClWCwAIAAkHAAoM"
    "AAsADAEAJG5ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L0NvbXBvbmVudAEAB2xpdGVyYWwBAEEoTGphdmEvbGFu"
    "Zy9TdHJpbmc7KUxuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9NdXRhYmxlQ29tcG9uZW50OwkADgAPBwAQDAAR"
    "ABIBACBuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9TdHlsZQEABUVNUFRZAQAiTG5ldC9taW5lY3JhZnQvbmV0"
    "d29yay9jaGF0L1N0eWxlOwcAFAEALW5ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L0NsaWNrRXZlbnQkT3BlblVy"
    "bAoAFgAXBwAYDAAZABoBAAxqYXZhL25ldC9VUkkBAAZjcmVhdGUBACIoTGphdmEvbGFuZy9TdHJpbmc7KUxqYXZh"
    "L25ldC9VUkk7CgATABwMAAUAHQEAEShMamF2YS9uZXQvVVJJOylWCgAOAB8MACAAIQEADndpdGhDbGlja0V2ZW50"
    "AQBLKExuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9DbGlja0V2ZW50OylMbmV0L21pbmVjcmFmdC9uZXR3b3Jr"
    "L2NoYXQvU3R5bGU7CgAjACQHACUMACYAJwEAK25ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L011dGFibGVDb21w"
    "b25lbnQBAAl3aXRoU3R5bGUBAFEoTG5ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L1N0eWxlOylMbmV0L21pbmVj"
    "cmFmdC9uZXR3b3JrL2NoYXQvTXV0YWJsZUNvbXBvbmVudDsHACkBABNqYXZhL2xhbmcvRXhjZXB0aW9uBwArAQA1"
    "bmV0L21pbmVjcmFmdC9uZXR3b3JrL2NoYXQvQ2xpY2tFdmVudCRDb3B5VG9DbGlwYm9hcmQKACoALQwABQAuAQAV"
    "KExqYXZhL2xhbmcvU3RyaW5nOylWBwAwAQAjbmVvcnVubmVyX25lb2ZvcmdlL0NsaWNrYWJsZU1lc3NhZ2UBAARD"
    "b2RlAQAPTGluZU51bWJlclRhYmxlAQAMdGV4dFdpdGhMaW5rAQBTKExqYXZhL2xhbmcvU3RyaW5nO0xqYXZhL2xh"
    "bmcvU3RyaW5nOylMbmV0L21pbmVjcmFmdC9uZXR3b3JrL2NoYXQvTXV0YWJsZUNvbXBvbmVudDsBAA1TdGFja01h"
    "cFRhYmxlAQAKU291cmNlRmlsZQEAFUNsaWNrYWJsZU1lc3NhZ2UuamF2YQEADElubmVyQ2xhc3NlcwcAOgEAJW5l"
    "dC9taW5lY3JhZnQvbmV0d29yay9jaGF0L0NsaWNrRXZlbnQBAAdPcGVuVXJsAQAPQ29weVRvQ2xpcGJvYXJkADEA"
    "LwACAAAAAAACAAIABQAGAAEAMQAAAB0AAQABAAAABSq3AAGxAAAAAQAyAAAABgABAAAACgAJADMANAABADEAAAB3"
    "AAUABAAAADUquAAHsgANuwATWSu4ABW3ABu2AB62ACJNpwAaTiq4AAeyAA27ACpZK7cALLYAHrYAIk0ssAABAAAA"
    "GQAcACgAAgAyAAAAFgAFAAAADwAZABIAHAAQAB0AEQAzABMANQAAAAwAAlwHACj8ABYHACMAAgA2AAAAAgA3ADgA"
    "AAASAAIAEwA5ADsAGQAqADkAPAAZ"
)

CLASS_NAME_NEOFORGE = "neorunner_neoforge/ClickableMessage.class"


def clickable_message_class_neoforge() -> bytes:
    """Return the compiled neorunner_neoforge.ClickableMessage class bytes."""
    return base64.b64decode(_CLASS_B64_NEOFORGE)


__all__ = ["CLASS_NAME", "CLASS_NAME_NEOFORGE", "clickable_message_class", "clickable_message_class_neoforge"]
