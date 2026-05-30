This is intended to be read top to bottom even if you only need later sections. Some stuff implicitly references previous stuff. This is also mainly for reproducibility for what I did. There are probably better ways to do stuff.

# Compile/Recompile `raw-eth` for Arch

### hardware requirements

 - \>=2GiB of RAM (>=4GiB is probably better)
 - working network card with ethernet and wifi
 - USB drive with >=2GiB (for live OS USB)
 - a second formatted USB drive (any size)

### Drive setup and booting

If you already have the drive set up, and you just need to update the program, skip to after the NOTE paragraph. The first bit of the steps are for Windows PowerShell + MinGW + MSYS2.

download the most recent arch ISO torrent file from [here](https://archlinux.org/download/).

```pwsh
transmission-cli -w . archlinux-2026.05.01-x86_64.iso.torrent
rm archlinux-2026.05.01-x86_64.iso.torrent
```

If you don't have `transmission-cli`, either install it with `pacman -Sy mingw-w64-ucrt-x86_64-transmission-cli` or equivalent, or just use a different program. On Windows, you can get `dd` from either MSYS2 or MinGW. Probably you should also verify the ISO file hash (i.e. `sha256sum` or `get-filehash`), but I skipped that. Plug in the USB you want to boot to arch from if you haven't already. Use `get-physicaldisk` to list out the drive indices, and figure out the one you want to put arch onto. Then `dd` the ISO onto the drive. For me, it was drive index 3.

```pwsh
dd "if=archlinux-2026.05.01-x86_64.iso" "of=\\.\PhysicalDrive3" bs=4M
sync
```

You can use `cat.exe "\\.\PhysicalDrive3" | xxd | less` to scroll through and check roughly that it worked.

NOTE: later, you will need a second USB drive formatted with something that Linux can recognize; I think mine is FAT32. It should contain the `raw-eth.c` source code somewhere the drive, but I will assume it is in the root of the drive. If you really want to, you could type the whole program in Arch, but if you have the program pre-written, then probably don't do that. You can get `raw-eth.c` with `wget 'https://raw.githubusercontent.com/drizzt536/fpga-aes/main/software/raw-eth.c'`, or similar.

(assuming you are booting arch on the same device you are on), reboot without unplugging the USB and press the BIOS boot select button (Esc on my machine) and select the USB with the Arch ISO. The next menu depends on if it is UEFI or BIOS, but select the one that says something like "Arch Linux install medium" or "boot existing OS" or something. Once it goes into the text mode stuff, it should print a bunch of `[  OK  ]` things and then boot into Arch.

### Internet

After this, you should just follow the Arch installation guide step 1.7 to connect to the internet ([install](https://wiki.archlinux.org/title/Installation_guide) and [iwctl](https://wiki.archlinux.org/title/Iwd#iwctl)); I will skip some steps that sometimes are required, but that I didn't have to use on my machine. I didn't need to worry about `rfkill` or having to turn on any of the devices, so it was fairly straightforward to connect to the internet.


```zsh
iwctl
device list
station wlan0 scan
station wlan0 get-networks
station wlan0 connect <wifi name>
<enter password>
exit
```

I have no idea why it was `wlan0` for the interface name and not a predictable name. `ip link` should show `wlan0` as `UP`.

### GCC setup

The next step is to install GCC. I installed it into RAM since, after the first boot, it won't be needed anymore unless `raw-eth.c` changes. My machine only has 4GB of RAM and had no issues with RAM size.

```zsh
mkdir /mnt/ram
mount -t tmpfs tmpfs /mnt/ram
cd /mnt/ram
mkdir -p var/lib/pacman
mkdir -p var/cache/pacman/pkg
```

The installation steps depend on if you want to compile with glibc or musl. musl will give a smaller binary, but the setup is slightly more involved. glibc's binary is around 10-15x larger, and glibc is known for not being the best at static linking, which is why musl might be a better choice.

For glibc, use `pacman -Sy --root . --cachedir var/cache/pacman/pkg --noconfirm gcc`, and for musl, install `musl` in addition to `gcc`. Next, set up the PATH

```zsh
export PATH=/mnt/ram/bin:$PATH
export LD_LIBRARY_PATH=/mnt/ram/lib
ln -s /mnt/ram/usr/lib/musl /usr/lib/musl

ln -s /usr/include/asm-generic /usr/lib/musl/include/asm-generic
ln -s /usr/include/linux       /usr/lib/musl/include/linux
ln -s /usr/include/asm         /usr/lib/musl/include/asm
```

At this point, GCC should be installed and working. Use `gcc --version` or `musl-gcc --version` to check if you want. You also don't need the internet anymore, so it can be turned back off with `rfkill`. The next step is to do setup to compile the program. Rerun `ip link` and check what the name of the ethernet interface is. If it is `eth0`, then it is not using predictable naming. If it is something like `enp3s0`, then it is predictable naming. Both should work, just with program flag tweaks. Run `lsblk` before and after plugging in the second USB to see what the drive name is that has `raw-eth.c` on it; mine was `/dev/sdc1`. The last three symlinks are just so `musl-gcc` can find `<linux/if_packet.h>` and all the stuff it requires.

### Compilation

```zsh
mkdir /mnt/usb2
mount /dev/sdc1 /mnt/usb2
cd /mnt/usb2
ip link set enp3s0 arp off
systemctl stop 'systemd-network*'
```

The compilation command depends on if you are using glibc or musl. For glibc, it is `gcc raw-eth.c -O3 -static -o raw-eth`. For musl, it is `musl-gcc raw-eth.c -O3 -static -nodefaultlibs -lc -o raw-eth`. And then potentially you might also need to also include extra flags. Use something like `-DIFACE="'e','n','p','2','s','1'"` to give a full explicit name; `-DPREDICTABLE -DIFBUS="'2'" -DIFSLOT="'1'"` is the same thing. If bus 3, `-DIFBUS` can be ommitted, and if it is is slot 0, `-DIFSLOT` can be omitted. If it does not use predictable naming and also isn't eth0, use something like `-DISLOT="'1'"`, which would correspond to eth1. `-static` is really the only flag that is definitely required for the glibc build, but most of the flags are required for the musl build. Depending on what the MAC address is for the device on the other end, you might also want to use something like `-DST="0a,1b,2c,3d,4e,5f"`. The default destination address is `02:55:5d:bd:66:59`, which is the protocol's FPGA MAC address. A source MAC is not required since it is queried at runtime. The current version of GCC that Arch uses has C23 as the default, so `-std=gnu23` isn't required. You need root to use raw packets, but Arch is root-only by default, so it shouldn't matter. Turning ARP off and disabling `systemd-networkd` stuff is so the only packets that get sent on the ethernet port are ones the program explicitly sends, that way the other machine won't be able to discover its MAC address due to automatic port discovery mechanisms. `systemd-networkd` sends DHCP requests every few seconds in this specific Arch ISO build since its ethernet interface doesn't have an IP assigned by default, so the internet is just be disabled to stop it from sending anything. Alternatively, you can probably just assign an IP to enp3s0.

Or I guess you could use WSL or Docker or something and skip like 90% of this. But that would be quite lame of you.


# Run `raw-eth` on Arch Without Recompiling

Boot into the ISO and plug in the second USB the same way as to compile/recompile `raw-eth`. Skip internet setup and GCC installs, etc. I will assume the second USB is `/dev/sdc1` again.

```zsh
mount /dev/sdc1 /mnt
cd /mnt
ip link set enp3s0 arp off
systemctl stop 'systemd-network*'
./raw-eth
```


# Compile `raw-eth` on preinstalled Raspberry Pi OS

Boot normally and plug the secondary drive in. RPi OS has auto mounting, so the drive should show up on the desktop. Copy `raw-eth.c` to wherever you want using the file manager. I copied it to `~/raw-eth.c`. The first time you run it, you may need to install GCC.

```sh
sudo apt install gcc
gcc raw-eth.c -std=gnu23 -O3 -o raw-eth
sudo ip link set eth0 arp off
```

`-static` is not required because the OS is actually installed, so it can actually touch the disk, and the library files actually exist. And same deal as with Arch: you may or may not need to change the compile-time flags for the program. Rpi OS does not use predictable interface names, so most likely it will just be `eth0`, which is the default. However, you may still need to change the destination MAC address. Use `sudo ./raw-eth` to run. Depending on the version of Debian you are using, you might have to find an experimental package repository or build from source or something. As of writing this, Debian bookworm uses GCC 12.2, which doesn't have very good C23 support, and I don't know if it works, so I would recommend updating to trixie. GCC >=15 definitely works and GCC 14 probably works.


# Compile on something else that isn't Windows

Idk, just fill in the dots. There are plenty of ways to get it to work. Good luck.


# Compile on Windows

`raw-eth` doesn't work on Windows :P. Maybe something like WSL would work, but then you would still need a ton of work to make it so Windows doesn't do any port auto discovery packet messages.


# Extra notes

### Program commands

The program commands are `q` to exit, `r` to start over the current packet, and `k` to clear the screen in addition to starting over the current packet. 0-9 and a-f will write the next nibble of the packet payload, and once it gets to 46 bytes, it will automatically send the packet. All commands are case insensitive. The src and dst MAC address and ether type fields are filled in automatically by the program.

### Compilation errors

If `musl-gcc` says it can't find GCC, you probably forgot to add `/mnt/ram/bin` to PATH. If you are using `musl-gcc` and it can't find `<linux/if_packet.h>`, `<linux/ethtool.h>`, `<asm/errno.h>`, `<asm-generic/errno-base.h>`, or something similar, you probably forgot one of the symlinks in the earlier stage before compilation.

### Program startup failures

If the program exits with exit code 1 and errno=1, you probably forgot to run with root. If it exits with exit code 1 and says the interface lookup failed, you probably either forgot `-DPREDICTABLE`, or gave the wrong bus/slot.

### Generic program failures

If packets aren't being received, use `ethtool <iface>` on both devices to see if they detect the ethernet connection. It should say something like "Link detected: yes"; if it says "no", the cable is probably an issue. If the cable is not an issue, use something like `sudo tcpdump -i eth0 -e -X` to see if the packets are just being dropped by the program, or if they aren't being seen at all. It might be a MAC address mismatch or something if you are getting recv error messages.
