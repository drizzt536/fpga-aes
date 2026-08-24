#pragma once
#define SETJMP_H

#ifndef __x86_64__
	#error "setjmp.h is only implemented for x86-64"
#endif

#include "int-types.h"
#include "va-if.h"

typedef struct {
	u64 rip, rbx, rsp, rbp
	#ifdef _WIN32
		, rdi, rsi
	#endif
		, r12, r13, r14, r15
	#if defined(_WIN32) && defined(__APXF__)
		, r30, r31
	#endif
		;
} jmp_buf;

[[gnu::returns_twice]]
i64 setjmp(jmp_buf *penv);

[[noreturn]]
void longjmp1(jmp_buf *penv); // use if setjmp's caller doesn't care what the value is

[[noreturn]]
void longjmp2(jmp_buf *penv, i64 value);

#define longjmp(penv, value...) VA_IF(longjmp2(penv, value), longjmp1(penv), value)

#ifdef _WIN32
	#ifdef __APXF__
		#define dump_jmp_buf(buf) printf(                                                \
			"\trip = 0x%016zx\n"  "\trbx = %zu\n"  "\trsp = 0x%016zx\n"  "\trbp = %zu\n" \
			"\trsi = %zu\n"  "\trdi = %zu\n"  "\tr12 = %zu\n"  "\tr13 = %zu\n"           \
			"\tr14 = %zu\n"  "\tr15 = %zu\n"  "\tr30 = %zu\n"  "\tr31 = %zu\n",          \
			(buf).rip,	(buf).rbx,	(buf).rsp,	(buf).rbp,                               \
			(buf).rsi,	(buf).rdi,	(buf).r12,	(buf).r13,                               \
			(buf).r14,	(buf).r15,	(buf).r30,	(buf).r31                                \
		)
	#else
		#define dump_jmp_buf(buf) printf(                                                \
			"\trip = 0x%016zx\n"  "\trbx = %zu\n"  "\trsp = 0x%016zx\n"  "\trbp = %zu\n" \
			"\trsi = %zu\n"  "\trdi = %zu\n"  "\tr12 = %zu\n"  "\tr13 = %zu\n"           \
			"\tr14 = %zu\n"  "\tr15 = %zu\n",                                            \
			(buf).rip,	(buf).rbx,	(buf).rsp,	(buf).rbp,                               \
			(buf).rsi,	(buf).rdi,	(buf).r12,	(buf).r13,                               \
			(buf).r14,	(buf).r15 	                                                     \
		)
	#endif
#else
	// Linux. No APX split; all the new registers are volatile.
	#define dump_jmp_buf(buf) printf(                                                \
		"\trip = 0x%016zx\n"  "\trbx = %zu\n"  "\trsp = 0x%016zx\n"  "\trbp = %zu\n" \
		"\tr12 = %zu\n" "\tr13 = %zu\n" "\tr14 = %zu\n" "\tr15 = %zu\n",             \
		(buf).rip,	(buf).rbx,	(buf).rsp,	(buf).rbp,                               \
		(buf).r12,	(buf).r13, (buf).r14,	(buf).r15 	                             \
	)
#endif
