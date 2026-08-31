#pragma once
#define INT_TYPES_H

#include <stdint.h>

typedef int8_t   i8;
typedef int16_t  i16;
typedef int32_t  i32;
typedef int64_t  i64;
typedef __int128 i128;

typedef uint8_t  u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef unsigned __int128 u128;

#define U128_MIN  ((u128) 0)
#define U128_MAX  (~U128_MIN)

#define I128_MAX  ((i128) (U128_MAX >> 1))
#define I128_MIN  (-I128_MAX - 1)
