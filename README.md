# NeoRunner-Python
Built for a linux host, this program will download/run the latest neoforged server (others supported as well) and try to sync mods it finds into client side to sidestep modloader swaps and client/server upgrades. I am a huge fan of the automodpack mod for what it's worth, and ## shout-out to skidam for making that mod and giving me the idea. 


As always, big shout-out to # My wife Sage, who understands that after I get home from work all I really want to do is more work. I love her more than trees love carbon dioxide. and to my son, who is the whole reason I would ever touch minecraft in the first place, let alone get this involved with it.


Here is the idea behind the project:
run script, it handles a lot of stuff so you don't have to.
you don't have to know a ton about minecraft modding to get started.
you run the script, you enable RCON (so it can tell your clients what they need when they try to connect), and set other configs.
it runs in a tmux for persistence, optionally will autostart. It will get all the things it needs on first run. It will prompt for authentication when it needs to install software.


You put your mods in the mods folder, don't worry if they aren't supposed to go on the server. script will read the mod manifest and sort it out for you!
You try to connect, it offers modloader for client if none detected, if detected compares mods folders between client -> server, provides download link from server. (you have to open mc server, RCON, http server ports for WAN configurations)
client can save to %appdata%/.minecraft/mods or whatever mod dir. 

restart minecraft -> sees new mods -> connect to server and have fun! Or find a reason to do more work like me haha!



I vibe coded this for max efficiency in getting started, then manually tweaked it to actually work. Used ChatGPT, logs attached.
