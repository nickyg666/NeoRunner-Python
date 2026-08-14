"""Embedded bytecode for the clickable-link disconnect helper.

``ClickableMessage.textWithLink(String text, String url)`` is a tiny
``neorunner_client`` class that builds a ``MutableComponent`` whose trailing
URL carries a ``ClickEvent.OpenUrl``.  It is compiled against the Minecraft
``net.minecraft.network.chat`` API (class-file major 65 / Java 21, so it loads
on every JVM NeoForge supports) and embedded here as base64 so the jar patcher
can inject it without needing a JDK on the server.

The Java source is::

    package neorunner_client;

    import net.minecraft.network.chat.ClickEvent;
    import net.minecraft.network.chat.Component;
    import net.minecraft.network.chat.MutableComponent;
    import net.minecraft.network.chat.Style;
    import java.net.URI;

    public final class ClickableMessage {
        private ClickableMessage() {}

        public static MutableComponent textWithLink(String text, String url) {
            try {
                ClickEvent click = new ClickEvent.OpenUrl(URI.create(url));
                MutableComponent link = Component.literal(url)
                    .withStyle(Style.EMPTY.withClickEvent(click));
                return Component.literal(text).append(link);
            } catch (Exception e) {
                return Component.literal(text + " " + url);
            }
        }
    }
"""

import base64

_CLASS_B64 = (
    "yv66vgAAAEEATQoAAgADBwAEDAAFAAYBABBqYXZhL2xhbmcvT2JqZWN0AQAGPGluaXQ+AQADKClWBwAIAQAt"
    "bmV0L21pbmVjcmFmdC9uZXR3b3JrL2NoYXQvQ2xpY2tFdmVudCRPcGVuVXJsCgAKAAsHAAwMAA0ADgEADGph"
    "dmEvbmV0L1VSSQEABmNyZWF0ZQEAIihMamF2YS9sYW5nL1N0cmluZzspTGphdmEvbmV0L1VSSTsKAAcAEAwA"
    "BQARAQARKExqYXZhL25ldC9VUkk7KVYLABMAFAcAFQwAFgAXAQAkbmV0L21pbmVjcmFmdC9uZXR3b3JrL2No"
    "YXQvQ29tcG9uZW50AQAHbGl0ZXJhbAEAQShMamF2YS9sYW5nL1N0cmluZzspTG5ldC9taW5lY3JhZnQvbmV0"
    "d29yay9jaGF0L011dGFibGVDb21wb25lbnQ7CQAZABoHABsMABwAHQEAIG5ldC9taW5lY3JhZnQvbmV0d29y"
    "ay9jaGF0L1N0eWxlAQAFRU1QVFkBACJMbmV0L21pbmVjcmFmdC9uZXR3b3JrL2NoYXQvU3R5bGU7CgAZAB8M"
    "ACAAIQEADndpdGhDbGlja0V2ZW50AQBLKExuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9DbGlja0V2ZW50"
    "OylMbmV0L21pbmVjcmFmdC9uZXR3b3JrL2NoYXQvU3R5bGU7CgAjACQHACUMACYAJwEAK25ldC9taW5lY3Jh"
    "ZnQvbmV0d29yay9jaGF0L011dGFibGVDb21wb25lbnQBAAl3aXRoU3R5bGUBAFEoTG5ldC9taW5lY3JhZnQv"
    "bmV0d29yay9jaGF0L1N0eWxlOylMbmV0L21pbmVjcmFmdC9uZXR3b3JrL2NoYXQvTXV0YWJsZUNvbXBvbmVu"
    "dDsKACMAKQwAKgArAQAGYXBwZW5kAQBVKExuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9Db21wb25lbnQ7"
    "KUxuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9NdXRhYmxlQ29tcG9uZW50OwcALQEAE2phdmEvbGFuZy9F"
    "eGNlcHRpb24SAAAALwwAMAAxAQAXbWFrZUNvbmNhdFdpdGhDb25zdGFudHMBADgoTGphdmEvbGFuZy9TdHJp"
    "bmc7TGphdmEvbGFuZy9TdHJpbmc7KUxqYXZhL2xhbmcvU3RyaW5nOwcAMwEAIW5lb3J1bm5lcl9jbGllbnQv"
    "Q2xpY2thYmxlTWVzc2FnZQEABENvZGUBAA9MaW5lTnVtYmVyVGFibGUBAAx0ZXh0V2l0aExpbmsBAFMoTGph"
    "dmEvbGFuZy9TdHJpbmc7TGphdmEvbGFuZy9TdHJpbmc7KUxuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9N"
    "dXRhYmxlQ29tcG9uZW50OwEADVN0YWNrTWFwVGFibGUBAApTb3VyY2VGaWxlAQAVQ2xpY2thYmxlTWVzc2Fn"
    "ZS5qYXZhAQAQQm9vdHN0cmFwTWV0aG9kcwgAPQEAAwEgAQ8GAD8KAEAAQQcAQgwAMABDAQAkamF2YS9sYW5n"
    "L2ludm9rZS9TdHJpbmdDb25jYXRGYWN0b3J5AQCYKExqYXZhL2xhbmcvaW52b2tlL01ldGhvZEhhbmRsZXMk"
    "TG9va3VwO0xqYXZhL2xhbmcvU3RyaW5nO0xqYXZhL2xhbmcvaW52b2tlL01ldGhvZFR5cGU7TGphdmEvbGFu"
    "Zy9TdHJpbmc7W0xqYXZhL2xhbmcvT2JqZWN0OylMamF2YS9sYW5nL2ludm9rZS9DYWxsU2l0ZTsBAAxJbm5l"
    "ckNsYXNzZXMHAEYBACVuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9DbGlja0V2ZW50AQAHT3BlblVybAcA"
    "SQEAJWphdmEvbGFuZy9pbnZva2UvTWV0aG9kSGFuZGxlcyRMb29rdXAHAEsBAB5qYXZhL2xhbmcvaW52b2tl"
    "L01ldGhvZEhhbmRsZXMBAAZMb29rdXAAMQAyAAIAAAAAAAIAAgAFAAYAAQA0AAAAHQABAAEAAAAFKrcAAbEA"
    "AAABADUAAAAGAAEAAAALAAkANgA3AAEANAAAAGwAAwAEAAAAMLsAB1kruAAJtwAPTSu4ABKyABgstgAetgAi"
    "Tiq4ABIttgAosE0qK7oALgAAuAASsAABAAAAIwAkACwAAgA1AAAAFgAFAAAAEAAMABEAGwASACQAEwAlABQA"
    "OAAAAAYAAWQHACwAAwA5AAAAAgA6ADsAAAAIAAEAPgABADwARAAAABIAAgAHAEUARwAZAEgASgBMABk="
)

CLASS_NAME = "neorunner_client/ClickableMessage.class"


def clickable_message_class() -> bytes:
    """Return the compiled ``neorunner_client.ClickableMessage`` class bytes."""
    return base64.b64decode(_CLASS_B64)


# A second copy compiled under a different package (neorunner_neoforge) so the
# universal jar (the "neoforge" JPMS module) can host its own helper class
# without a cross-module reference to the "minecraft" module's copy. Java
# forbids two modules from exporting the same package, so each jar gets its own
# package. Same body as above.
_CLASS_B64_NEOFORGE = (
    "yv66vgAAAEEATQoAAgADBwAEDAAFAAYBABBqYXZhL2xhbmcvT2JqZWN0AQAGPGluaXQ+AQADKClWBwAIAQAtbmV0L21pbmVjcmFmdC9uZXR3b3JrL2NoYXQvQ2xpY2tFdmVudCRPcGVuVXJsCgAKAAsHAAwMAA0ADgEADGphdmEvbmV0L1VSSQEABmNyZWF0ZQEAIihMamF2YS9sYW5nL1N0cmluZzspTGphdmEvbmV0L1VSSTsKAAcAEAwABQARAQARKExqYXZhL25ldC9VUkk7KVYLABMAFAcAFQwAFgAXAQAkbmV0L21pbmVjcmFmdC9uZXR3b3JrL2NoYXQvQ29tcG9uZW50AQAHbGl0ZXJhbAEAQShMamF2YS9sYW5nL1N0cmluZzspTG5ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L011dGFibGVDb21wb25lbnQ7CQAZABoHABsMABwAHQEAIG5ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L1N0eWxlAQAFRU1QVFkBACJMbmV0L21pbmVjcmFmdC9uZXR3b3JrL2NoYXQvU3R5bGU7CgAZAB8MACAAIQEADndpdGhDbGlja0V2ZW50AQBLKExuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9DbGlja0V2ZW50OylMbmV0L21pbmVjcmFmdC9uZXR3b3JrL2NoYXQvU3R5bGU7CgAjACQHACUMACYAJwEAK25ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L011dGFibGVDb21wb25lbnQBAAl3aXRoU3R5bGUBAFEoTG5ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L1N0eWxlOylMbmV0L21pbmVjcmFmdC9uZXR3b3JrL2NoYXQvTXV0YWJsZUNvbXBvbmVudDsKACMAKQwAKgArAQAGYXBwZW5kAQBVKExuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9Db21wb25lbnQ7KUxuZXQvbWluZWNyYWZ0L25ldHdvcmsvY2hhdC9NdXRhYmxlQ29tcG9uZW50OwcALQEAE2phdmEvbGFuZy9FeGNlcHRpb24SAAAALwwAMAAxAQAXbWFrZUNvbmNhdFdpdGhDb25zdGFudHMBADgoTGphdmEvbGFuZy9TdHJpbmc7TGphdmEvbGFuZy9TdHJpbmc7KUxqYXZhL2xhbmcvU3RyaW5nOwcAMwEAI25lb3J1bm5lcl9uZW9mb3JnZS9DbGlja2FibGVNZXNzYWdlAQAEQ29kZQEAD0xpbmVOdW1iZXJUYWJsZQEADHRleHRXaXRoTGluawEAUyhMamF2YS9sYW5nL1N0cmluZztMamF2YS9sYW5nL1N0cmluZzspTG5ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L011dGFibGVDb21wb25lbnQ7AQANU3RhY2tNYXBUYWJsZQEAClNvdXJjZUZpbGUBABVDbGlja2FibGVNZXNzYWdlLmphdmEBABBCb290c3RyYXBNZXRob2RzCAA9AQADASABDwYAPwoAQABBBwBCDAAwAEMBACRqYXZhL2xhbmcvaW52b2tlL1N0cmluZ0NvbmNhdEZhY3RvcnkBAJgoTGphdmEvbGFuZy9pbnZva2UvTWV0aG9kSGFuZGxlcyRMb29rdXA7TGphdmEvbGFuZy9TdHJpbmc7TGphdmEvbGFuZy9pbnZva2UvTWV0aG9kVHlwZTtMamF2YS9sYW5nL1N0cmluZztbTGphdmEvbGFuZy9PYmplY3Q7KUxqYXZhL2xhbmcvaW52b2tlL0NhbGxTaXRlOwEADElubmVyQ2xhc3NlcwcARgEAJW5ldC9taW5lY3JhZnQvbmV0d29yay9jaGF0L0NsaWNrRXZlbnQBAAdPcGVuVXJsBwBJAQAlamF2YS9sYW5nL2ludm9rZS9NZXRob2RIYW5kbGVzJExvb2t1cAcASwEAHmphdmEvbGFuZy9pbnZva2UvTWV0aG9kSGFuZGxlcwEABkxvb2t1cAAxADIAAgAAAAAAAgACAAUABgABADQAAAAdAAEAAQAAAAUqtwABsQAAAAEANQAAAAYAAQAAAAoACQA2ADcAAQA0AAAAcAADAAQAAAAwuwAHWSu4AAm3AA9NK7gAErIAGCy2AB62ACJOKrgAEi22ACiwTSorugAuAAC4ABKwAAEAAAAjACQALAACADUAAAAaAAYAAAAOAAwADwAUABAAGwARACQAEgAlABMAOAAAAAYAAWQHACwAAwA5AAAAAgA6ADsAAAAIAAEAPgABADwARAAAABIAAgAHAEUARwAZAEgASgBMABk="
)

CLASS_NAME_NEOFORGE = "neorunner_neoforge/ClickableMessage.class"


def clickable_message_class_neoforge() -> bytes:
    """Return the compiled ``neorunner_neoforge.ClickableMessage`` class bytes."""
    return base64.b64decode(_CLASS_B64_NEOFORGE)


__all__ = ["CLASS_NAME", "CLASS_NAME_NEOFORGE", "clickable_message_class", "clickable_message_class_neoforge"]

