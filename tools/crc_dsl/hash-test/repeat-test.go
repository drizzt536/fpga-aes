// things it flags as collisions are not necessarily collisions
// go build -ldflags="-s -w" -gcflags="-B" -o repeat-test.exe repeat-test.go common.go

package main

import "fmt"

var hashMap = make(map[uint64]struct{}) // hash set
var count uint64 = 0
var collisions uint64 = 0

func check(data []byte) {
	h := jhash64(data)
	count++

	if count&printout_thresh == 0 {
		fmt.Printf("\rProcessed: %s", formatCommas(count))
	}

	if _, exists := hashMap[h]; exists {
		// not provable, but very likely is a collision
		collisions++
		return
	}

	hashMap[h] = struct{}{}
}
