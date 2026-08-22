// test for full hash collisions
// this doesn't really say anything about the hash function beyond that it isn't abysmally terrible.
// all reported hash collisions are true collisions
// go build -ldflags="-s -w" -gcflags="-B" -o collision-test.exe collision-test.go common.go

package main

import (
	"fmt"
	"os"
)

var hashMap = make(map[uint64][]string)
var count uint64
var collisions uint64 = 0

func check(data []byte) {
	h := jhash64(data)
	count++

	if count&printout_thresh == 0 {
		fmt.Printf("\rProcessed: %s", formatCommas(count))
	}

	existing, exists := hashMap[h]
	dataStr          := string(data)

	if !exists {
		hashMap[h] = []string{dataStr}
		return
	}

	for _, v := range existing {
		if v == dataStr {
			return
		}
	}

	hashMap[h] = append(existing, dataStr)

	collisions++
	fmt.Fprintf(os.Stderr, "\r\x1b[K[!] COLLISION FOUND [Hash: %d]\n", h)
	for i, val := range hashMap[h] {
		fmt.Fprintf(os.Stderr, " -> Item %d: %x (hex)\n", i + 1, []byte(val))
	}
}
