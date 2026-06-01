/// Raspberry Pi OS
// setup   : sudo ip link set eth0 arp off
// compile : gcc raw-eth.c -std=gnu23 -Werror -Wall -Wextra -O3 -o raw-eth
// run     : sudo ./raw-eth

/// Arch
// setup     : ip link set enp3s0 arp off
// compile 1 : gcc raw-eth.c -std=gnu23 -Werror -Wall -Wextra -O3 -static -DPREDICTABLE -o raw-eth
// compile 2 : musl-gcc raw-eth.c -std=gnu23 -O3 -static -nodefaultlibs -lc -DPREDICTABLE -o raw-eth
// run       : ./raw-eth

#include <stdio.h>
#include <string.h>
#include <stdint.h>
#include <stdlib.h>

// these usage lists aren't exhaustive anymore
#include <fcntl.h>				// fcntl, F_SETFL, F_GETFL, O_NONBLOCK
#include <errno.h>				// errno, EAGAIN
#include <termios.h>			// struct termios, tc[gs]etattr, TCSANOW, ECHO, ICANON
#include <unistd.h>				// read, close
#include <sys/socket.h>			// socket, sendto, recv, AF_PACKET, SOCK_RAW
#include <sys/ioctl.h>			// ioctl, SIOCGIFINDEX, SIOCGIFHWADDR
#include <net/if.h>				// struct ifreq
#include <linux/if_packet.h>	// struct sockaddr_ll, struct sockaddr
#include <linux/ethtool.h>		// struct ethtool_(value|cmd), ETHTOOL_G(LINK|SET), DUPLEX_FULL
#include <linux/sockios.h>		// SIOCETHTOOL, SIOCGIFFLAGS

#if __BYTE_ORDER__ != __ORDER_LITTLE_ENDIAN__
	#error "byte order must be little endian"
#endif

#define _VA_ID_IGNORED(...)
#define _VA_ID(x...) x
#define _VA_ID_IF(suffix, x...) _VA_ID ## suffix(x)
#define VA_IF(t, f, ...) __VA_OPT__(t) _VA_ID_IF(__VA_OPT__(_IGNORED), f)

#define ERR_STT			"\e[38;2;166;12;26mERROR: "
#define FORCE_INLINE	inline __attribute__((always_inline, gnu_inline))
#define PAYLOAD_LEN		46
#define PACKET_LEN		(PAYLOAD_LEN + 2*6 + 2)
#define NS_ETH_TYPE		0xb588 // htons(0x88b5)

#define RED(s)			"\e[31m" s "\e[m"
#define GREEN(s)		"\e[32m" s "\e[m"

#ifndef IFACE
	#ifdef PREDICTABLE  // predictable network interface names
		// e.g. -DPREDICTABLE -DIFBUS="'2'" -DIFSLOT="'0'"

		// guess it is PCI bus 3 slot 0. use `ip link` for the real name.
		#ifndef IFBUS
			#define IFBUS '3'
		#endif

		#ifndef IFSLOT
			#define IFSLOT '0'
		#endif

		#define IFACE 'e','n','p',IFBUS,'s',IFSLOT
	#else
		// probably there is only one ethernet port, so guess it is eth0

		#ifndef IFSLOT
			// repurpose the same macro name as in the predictable branch
			#define IFSLOT '0'
		#endif

		#define IFACE 'e','t','h',IFSLOT
	#endif
#endif

#define _AND2(x, y) x && y
#define _AND1(x) x && x
#define AND(x, y...) VA_IF(_AND2(x, y), _AND1(x), y)

typedef uint8_t  u8;
typedef uint16_t u16;
typedef  int32_t i32;
typedef uint32_t u32;
typedef  int64_t i64;

static char hex_chars[16] = {
	'0', '1', '2', '3', '4', '5', '6', '7',
	'8', '9', 'a', 'b', 'c', 'd', 'e', 'f',
};

static struct termios term_settings;

static void apply_term_settings(void) {
	tcsetattr(0, TCSANOW, &term_settings);
}

//////////////////////////////////// packet stuff ////////////////////////////////////

#define _MAC(x1, x2, x3, x4, x5, x6) 0x##x1, 0x##x2, 0x##x3, 0x##x4, 0x##x5, 0x##x6
#define MAC(...) _MAC(__VA_ARGS__)

#ifndef ST
	// I like this number: "0" <> ToString@BaseForm[Floor[16^12 / (
	//     (GoldenRatio^(EulerGamma Sqrt[2]) + Pi^E) Sqrt[21]
	// )], 16] ~StringTake~ 12

	#define ST 02,55,5d,bd,66,59
#endif

#define DST_MAC MAC(ST)

typedef union {
	u8 raw[PACKET_LEN];

	__attribute__((packed)) struct {
		u8 dst_mac[6];
		u8 src_mac[6];

		union {
			u8 type[2];
			u16 utype;
		};

		u8 payload[PAYLOAD_LEN];
	};
} EthernetPacket;

static EthernetPacket out_packet = {
	.dst_mac = {DST_MAC},
	.src_mac = {}, // filled at runtime
	.utype   = NS_ETH_TYPE,
	.payload = {},
};

static EthernetPacket in_packet = {};

static i32 sockfd = 0;
static struct sockaddr_ll addr = {0};

static FORCE_INLINE void _log_packet2(u8 *pkt, u8 maxbytes) {
	// pass a pointer to the payload itself
	if (maxbytes > PAYLOAD_LEN)
		maxbytes = PAYLOAD_LEN;

	for (u8 i = 0; i < maxbytes; i++)
		printf("%02x", pkt[i]);
}

static FORCE_INLINE void _log_packet1(u8 *pkt) {
	_log_packet2(pkt, PAYLOAD_LEN);
}

#define log_packet(pkt, maxlen...) VA_IF(_log_packet2(pkt, maxlen), _log_packet1(pkt), maxlen)

static u8 send_packet(bool debug) {
	// 0 => success, 1 => miscellaneous failure
	if (debug) {
		printf("\rsend: ");
		log_packet(out_packet.payload);
	}

	const bool failure = -1ll == sendto(
		sockfd, out_packet.raw, PACKET_LEN, /*flags*/ 0,
		(struct sockaddr *) &addr, sizeof addr
	);

	if (debug) {
		putchar('.');
		putchar(' ');
		printf(failure ? RED("fail") : "pass");
		putchar('\n');
	}

	return (u8) failure;
}

static u8 recv_packet(bool debug) {
	// 0 => success, 1 => no packet available, 2 => FPGA bypass attempt, 3 => EtherType mismatch, 4 => some other error

	const bool success = -1ll != recv(sockfd, in_packet.raw, PACKET_LEN, MSG_DONTWAIT);

	if (success) {
		if (memcmp(in_packet.src_mac, out_packet.dst_mac, 6) != 0 || memcmp(in_packet.dst_mac, out_packet.src_mac, 6) != 0) {
			// there should only be two devices on the network. if there is a packet from
			// some address other than the one it should be talking to, that is an error.
			// Also, if the packet's destination doesn't match the current device's MAC, then
			// probably it was a broadcast or multicast, which should be discarded so the two
			// devices cannot talk to each other without the FPGA in the middle
			return 2;
		}

		if (in_packet.utype != out_packet.utype)
			return 3;

		if (debug) {
			printf("\rrecv: ");
			log_packet(in_packet.payload);
			putchar('\n');
		}

		return 0;
	}

	return errno == EAGAIN ? 1 : 4;
}

////////////////////////////////// packet stuff end //////////////////////////////////

int main(void) {
	sockfd = socket(AF_PACKET, SOCK_RAW, NS_ETH_TYPE);

	if (sockfd < 0) {
		printf(ERR_STT "socket could not be opened. errno: %d.\e[m\n", errno);
		return 1;
	}

	{
		struct ifreq ifr = {.ifr_name = {IFACE, '\0'}};

		// index lookup
		if (ioctl(sockfd, SIOCGIFINDEX, &ifr) < 0) {
			printf(ERR_STT "interface lookup failed. name: %s. errno: %d\e[m\n", ifr.ifr_name, errno);
			return 1;
		}

		printf("using interface %d: %s\n", ifr.ifr_ifindex, ifr.ifr_name);
		addr.sll_ifindex = ifr.ifr_ifindex;

		// MAC lookup
		if (ioctl(sockfd, SIOCGIFHWADDR, &ifr) < 0) {
			printf(ERR_STT "src MAC lookup failed. errno: %d\e[m\n", errno);
			return 1;
		}

		memcpy(out_packet.src_mac, ifr.ifr_hwaddr.sa_data, 6);

		// link status lookup
		struct ethtool_value ethval;
		ethval.cmd = ETHTOOL_GLINK;
		ifr.ifr_data = (void *) &ethval;

		if (ioctl(sockfd, SIOCETHTOOL, &ifr) < 0) {
			printf(ERR_STT "link status lookup failed. errno=%d\e[m\n", errno);
			return 1;
		}

		// ARP and interface status lookup
		if (ioctl(sockfd, SIOCGIFFLAGS, &ifr) < 0) {
			printf(ERR_STT "interface flag lookup failed. errno=%d\e[m\n", errno);
			return 1;
		}

		printf("interface %s, link %s, ARP %s, promisc %s\n",
			!!(ifr.ifr_flags & IFF_UP)      ? GREEN("UP")  : RED("DOWN"),
			ethval.data                     ? GREEN("UP")  : RED("DOWN"),
			!!(ifr.ifr_flags & IFF_NOARP)   ? GREEN("OFF") : RED("ON"),
			!!(ifr.ifr_flags & IFF_PROMISC) ? RED("ON")    : GREEN("OFF")
		);

		// link details lookup
		struct ethtool_cmd ethcmd;
		ethcmd.cmd = ETHTOOL_GSET;
		ifr.ifr_data = (void *) &ethcmd;

		if (ioctl(sockfd, SIOCETHTOOL, &ifr) < 0) {
			printf(ERR_STT "link details lookup failed. errno=%d\e[m\n", errno);
			return 1;
		}

		const u32 link_speed = ethtool_cmd_speed(&ethcmd);

		printf("%uMbps%s, %s duplex, autoneg %s\n",
			link_speed,
			link_speed < 1000 && (ethcmd.supported & (
				SUPPORTED_1000baseT_Full | SUPPORTED_1000baseT_Half
			)) ? ", local supports gigabit" : "",
			ethcmd.duplex  == DUPLEX_FULL    ? GREEN("full") : RED("half"),
			ethcmd.autoneg == AUTONEG_ENABLE ? GREEN("ON")   : RED("OFF")
		);
	}

	printf("src MAC: %02x:%02x:%02x:%02x:%02x:%02x\n",
		out_packet.src_mac[0], out_packet.src_mac[1], out_packet.src_mac[2],
		out_packet.src_mac[3], out_packet.src_mac[4], out_packet.src_mac[5]
	);

	printf("dst MAC: %02x:%02x:%02x:%02x:%02x:%02x\n",
		out_packet.dst_mac[0], out_packet.dst_mac[1], out_packet.dst_mac[2],
		out_packet.dst_mac[3], out_packet.dst_mac[4], out_packet.dst_mac[5]
	);

	printf("EtherType: 0x%02x%02x\n", out_packet.type[0], out_packet.type[1]);

	fcntl(0, F_SETFL, fcntl(0, F_GETFL) | O_NONBLOCK);

#ifdef __GLIBC__
	#define ugetchar() (getchar() | 32)
#else
	#define ugetchar() ({u8 ch; read(0, &ch, 1) == 1 ? (i32) (ch | 32) : EOF;})

	// musl needs this for some reason to stop doing line buffering
	freopen(NULL, "w", stdout);
	setvbuf(stdout, NULL, _IONBF, 0);
#endif

	tcgetattr(0, &term_settings);

	term_settings.c_lflag &= ~(ECHO | ICANON);
#ifndef __GLIBC__
	term_settings.c_cc[VMIN] = 0;
#endif
	apply_term_settings();

	term_settings.c_lflag |= ECHO | ICANON;
#ifndef __GLIBC__
	term_settings.c_cc[VMIN] = 1;
#endif
	atexit(apply_term_settings);

	_Static_assert(2*PAYLOAD_LEN < 256, "PAYLOAD_LEN must fit in half a byte");
	u8 nib_idx = 0;

	while (true) {
		u8 nib;
		const i32 c = ugetchar();

		// alternate checking stdin for chars and socket for packets

		if (c != EOF) {
			if (c == 'q') {
				puts("Quit");
				return 0;
			}

			if (c == 'r') {
				printf("\r\e[K");
				nib_idx = 0;
				continue;
			}

			if (c == 'k') {
				printf("\e[3J\e[2J\e[H");
				nib_idx = 0;
				continue;
			}

			if      ('0' <= AND(c) <= '9') nib = c - '0';
			else if ('a' <= AND(c) <= 'f') nib = c - 'a' + 10;
			else continue;

			// only log the character if it is valid
			putchar(c);

			if (nib_idx & 1) out_packet.payload[nib_idx >> 1] |= nib;
			else             out_packet.payload[nib_idx >> 1]  = nib << 4;

			if (++nib_idx == 2*PAYLOAD_LEN) {
				// TODO: do something with the output packets
				send_packet(true);
				nib_idx = 0;
			}
		}

		const u8 recv_code = recv_packet(true);

		if (recv_code == 1)
			// no packet available
			continue;

		if      (recv_code == 0); // TODO: do something with the input packets
		else if (recv_code == 2)
			// TODO: perhaps disconnect or timeout or something in this case?
			printf("\rrecv: broadcast attempt or third party device\e[K\n");
		else if (recv_code == 3) printf(
			"\rrecv: EtherType mismatch. expected 0x%02x%02x and received 0x%02x%02x.\e[K\n",
			out_packet.type[0], out_packet.type[1], in_packet.type[0], in_packet.type[1]
		);
		else if (recv_code == 4) printf("\rrecv: miscellaneous error: %u\e[K\n", errno);
		else                     printf("\rrecv: unknown failure code: %u, errno=%u\e[K\n", recv_code, errno);

		// restore the partially-written output packet to the terminal
		log_packet(out_packet.payload, nib_idx >> 1);

		if (nib_idx & 1)
			putchar(hex_chars[ out_packet.payload[nib_idx >> 1] >> 4 ]);
	} // while true

	return 0;
}
