// common functions to both the collision and repeat detectors.

package main

import (
	"crypto/rand"
	"encoding/binary"
	"fmt"
	"math"
	"math/big"
	"math/bits"
	"os"
	"os/signal"
	"strconv"
	"syscall"
)

var hash_mask uint64  = 0xffffffffffffffff
const printout_thresh = 0xfffff

func jhash_mulhi64(x, y uint64) uint64 {
	hi, _ := bits.Mul64(x, y)
	return hi
}

func jhash64(data []byte) uint64 {
	key := uint64(0)

	const (
		p1 = 0x6a09e667f3bcc909
		p2 = 0x3c6ef372fe94f82c
		p3 = 0xc4ceb9fe1a85ec53
		mx = 0xff51afd7ed558ccd
		x1 = 0x736f6d6570736575
		x2 = 0x6c7967656e657261
		x3 = 0x25232284e49cf2cb
	)

	n := uint64(len(data))

	hash := bits.ReverseBytes64(key ^ x1) | 1
	rkey := (key ^ x2) | 1
	var fbkh uint64

	key  ^= x3
	rkey += p2

	for n >= 8 {
		fbkh  = hash
		n    -= 8
		hash ^= binary.LittleEndian.Uint64(data)
		tmp  := jhash_mulhi64(fbkh, rkey)
		hash *= p1
		data  = data[8:]
		hash ^= tmp
		rkey += p2
	}

	if n > 0 {
		chunk := n << (7*8)
		fbkh = hash

		switch n {
			case 7: chunk |= uint64(data[6]) << (6*8); fallthrough
			case 6: chunk |= uint64(data[5]) << (5*8); fallthrough
			case 5: chunk |= uint64(data[4]) << (4*8); fallthrough
			case 4: chunk |= uint64(data[3]) << (3*8); fallthrough
			case 3: chunk |= uint64(data[2]) << (2*8); fallthrough
			case 2: chunk |= uint64(data[1]) << (1*8); fallthrough
			case 1: chunk |= uint64(data[0]) << (0*8)
		}

		hash ^= chunk
		hash *= p1
		hash ^= jhash_mulhi64(fbkh, rkey)
	}

	hash ^= jhash_mulhi64(hash, key | 1)
	hash *= p3
	fbkh  = hash
	hash *= mx
	hash  = bits.ReverseBytes64(hash)
	hash ^= hash >> 13
	hash ^= fbkh
	return hash
}

func formatCommas(n uint64) string {
	in := fmt.Sprintf("%d", n)
	var out []byte

	for i := 0; i < len(in); i++ {
		if i > 0 && (len(in) - i)%3 == 0 {
			out = append(out, ',')
		}

		out = append(out, in[i])
	}

	return string(out)
}

func randInt(max int64) int64 {
	n, err := rand.Int(rand.Reader, big.NewInt(max))

	if err != nil {
		panic(err)
	}

	return n.Int64()
}

const actualMinLen = 4

func main() {
	// exit gracefully on ^C
	c := make(chan os.Signal, 1)
	signal.Notify(c, os.Interrupt, syscall.SIGTERM)

	go func() {
		<-c
		// copy to local variables to make data race not as bad
		_unique     := uint64(len(hashMap))
		_count      := count
		_collisions := collisions

		_mask_popcount := bits.OnesCount64(hash_mask)
		_M             := 1.0 * float64(uint64(1) << uint(_mask_popcount))

		_lambda := float64(_count) * float64(_count) / (2 * _M)
		_z      := (float64(_collisions) - _lambda) / math.Sqrt(_lambda)

		fmt.Printf(
			"\n\nSearch manually stopped.\n" +
			"total hashes  : %s\n"  +
			"unique hashes : %s\n" +
			"collisions    : %s\n" +
			"lambda        : %f\n" +
			"z             : %f\n",
			formatCommas(_count),
			formatCommas(_unique),
			formatCommas(_collisions),
			_lambda,
			_z,
		)

		os.Exit(0)
	}()

	minLen := uint64(actualMinLen)
	maxLen := uint64(64)

	switch len(os.Args) - 1 {
	case 0:
		// use defaults
	case 1:
		// 1 arg: (actualMinLen, arg1, full mask)
		n, err := strconv.ParseUint(os.Args[1], 10, 64)
		if err != nil {
			fmt.Fprintln(os.Stderr, "Max length must be a non-negative integer")
			os.Exit(1)
		}
		maxLen = uint64(n)
	case 2:
		// 2 args: (arg1, arg2, full mask)
		n1, err1 := strconv.ParseUint(os.Args[1], 10, 64)
		n2, err2 := strconv.ParseUint(os.Args[2], 10, 64)

		if err1 != nil || err2 != nil {
			fmt.Fprintln(os.Stderr, "Arguments must be non-negative integers")
			os.Exit(1)
		}

		minLen = uint64(n1)
		maxLen = uint64(n2)
	case 3:
		// 2 args: (arg1, arg2, full mask)
		n1, err1 := strconv.ParseUint(os.Args[1], 10, 64)
		n2, err2 := strconv.ParseUint(os.Args[2], 10, 64)
		n3, err3 := strconv.ParseUint(os.Args[3], 0, 64)

		if err1 != nil || err2 != nil || err3 != nil {
			fmt.Fprintln(os.Stderr, "Arguments must be non-negative integers")
			os.Exit(1)
		}

		minLen    = uint64(n1)
		maxLen    = uint64(n2)
		hash_mask = uint64(n3)
	default:
		fmt.Fprintln(os.Stderr, "Expected at most three arguments: [min_length] [max_length] [mask]")
		os.Exit(1)
	}

	if minLen < actualMinLen {
		fmt.Fprintf(os.Stderr, "Error: minimum length must be at least %d\n", actualMinLen + 1)
		os.Exit(1)
	}

	if minLen > maxLen {
		fmt.Fprintln(os.Stderr, "Error: minimum length cannot be greater than maximum length")
		os.Exit(1)
	}


	fmt.Printf("asdf => 0x%016x\n", jhash64([]byte("asdf")))
	fmt.Printf("qwer => 0x%016x\n", jhash64([]byte("qwer")))
	fmt.Printf("1234 => 0x%016x\n", jhash64([]byte("1234")))

	mask_popcount := uint64(bits.OnesCount64(hash_mask))

	fmt.Printf(
		"Mask: 0x%016x (popcount=%d)\n" +
		"    Quick check   (λ=100):  N = %s\n" +
		"    Solid check   (λ=500):  N = %s\n" +
		"    Thorough      (λ=2000): N = %s\n",
		hash_mask, mask_popcount,
		formatCommas( uint64(math.Sqrt( float64((uint64(2) << mask_popcount) * 100 ) )) ),
		formatCommas( uint64(math.Sqrt( float64((uint64(2) << mask_popcount) * 500 ) )) ),
		formatCommas( uint64(math.Sqrt( float64((uint64(2) << mask_popcount) * 2000) )) ),
	)

	// Exhaustive Phase
	check([]byte{0})

	for i1 := 0; i1 < 256; i1++ {
		check([]byte{byte(i1)})

		for i2 := 0; i2 < 256; i2++ {
			check([]byte{byte(i1), byte(i2)})

			for i3 := 0; i3 < 256; i3++ {
				check([]byte{byte(i1), byte(i2), byte(i3)})
			}
		}
	}

	fmt.Printf("\rexhaustive phase checked %s inputs, up to length %d\n", formatCommas(count), actualMinLen - 1);

	// Infinite Random Phase
	fmt.Printf("Starting infinite random search (Lengths %d to %d)...\n", minLen, maxLen)
	fmt.Println("Press Ctrl+C to stop.")

	// Reusable static buffer based on the largest possible size
	buf := make([]byte, maxLen)

	for {
		// Pick random length from minLen to maxLen (inclusive)
		length := int(randInt(int64(maxLen - minLen + 1))) + int(minLen)

		for i := 0; i < 10; i++ {
			for k := 0; k < length; k++ {
				buf[k] = byte(randInt(256))
			}

			check(buf[:length])
		}
	}
}
