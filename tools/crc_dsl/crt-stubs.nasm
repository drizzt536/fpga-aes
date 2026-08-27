%ifndef CRT_STUBS
%define CRT_STUBS

bits 64

;; the stack stuff and mingw stuff is required for GMP to work properly

;; the setjmp/longjmp stuff only works properly if SEH is disabled since it completely
;; ignores exception stuff. it also doesn't do anything for floating-point state.
;; If xmm/float stuff matters, just use the actual setjmp/longjmp

%assign APX		%isdef(APX)
%assign LINUX	%isdef(LINUX)
%assign WINDOWS	!LINUX

%ifndef PAGE_SIZE
	%define PAGE_SIZE 4096
%endif

global setjmp, longjmp1, longjmp2, __stack_chk_fail, __stack_chk_guard
extern abort

%if WINDOWS
	global ___chkstk_ms, __mingw_vfprintf
	extern vfprintf

	%define arg1 rcx
	%define arg2 rdx
%else
	global _start
	extern main, exit

	%define arg1 rdi
	%define arg2 rsi
%endif

struc jmp_buf
	.rip: resq 1

	.rbx: resq 1

	.rsp: resq 1
	.rbp: resq 1

%if WINDOWS
	.rdi: resq 1
	.rsi: resq 1
%endif

	.r12: resq 1
	.r13: resq 1
	.r14: resq 1
	.r15: resq 1

%if APX && WINDOWS
	.r30: resq 1
	.r31: resq 1
%endif
endstruc

section .text

setjmp: ; i64 setjmp(jmp_buf *penv);
	mov 	rax, [rsp]	; read the return address
	mov 	qword [arg1 + jmp_buf.rip], rax

	mov 	qword [arg1 + jmp_buf.rbx], rbx

	lea 	rax, [rsp + 8]					;; counteract the rsp -= 8 from the CALL instruction.
	mov 	qword [arg1 + jmp_buf.rsp], rax
	mov 	qword [arg1 + jmp_buf.rbp], rbp

%if WINDOWS
	mov 	qword [arg1 + jmp_buf.rdi], rdi
	mov 	qword [arg1 + jmp_buf.rsi], rsi
%endif

	mov 	qword [arg1 + jmp_buf.r12], r12
	mov 	qword [arg1 + jmp_buf.r13], r13
	mov 	qword [arg1 + jmp_buf.r14], r14
	mov 	qword [arg1 + jmp_buf.r15], r15

%if WINDOWS && APX
	mov 	qword [arg1 + jmp_buf.r30], r30
	mov 	qword [arg1 + jmp_buf.r31], r31
%endif

	xor 	eax, eax
	ret

longjmp1: ; void longjmp1(jmp_buf *penv);
;	xor 	edx, edx
longjmp2: ; void longjmp2(jmp_buf *penv, u64 value);
	mov 	rbx, qword [arg1 + jmp_buf.rbx]

	mov 	rsp, qword [arg1 + jmp_buf.rsp]
	mov 	rbp, qword [arg1 + jmp_buf.rbp]

%if WINDOWS
	mov 	rdi, qword [arg1 + jmp_buf.rdi]
	mov 	rsi, qword [arg1 + jmp_buf.rsi]
%endif

	mov 	r12, qword [arg1 + jmp_buf.r12]
	mov 	r13, qword [arg1 + jmp_buf.r13]
	mov 	r14, qword [arg1 + jmp_buf.r14]
	mov 	r15, qword [arg1 + jmp_buf.r15]

%if WINDOWS && APX
	mov 	r30, qword [arg1 + jmp_buf.r30]
	mov 	r31, qword [arg1 + jmp_buf.r31]
%endif

	mov 	eax, 1
	test	arg2, arg2
	cmovnz	rax, arg2		; rax = value ?: 1;
	jmp 	qword [arg1 + jmp_buf.rip]

;; OS-specific stuff
%if WINDOWS
___chkstk_ms: ; void ___chkstk_ms(i64 size);
	push	rax
	push	rcx
	mov 	rcx, rsp		; char *ptr = __builtin_frame_address(0);

.loop:						; do {
	sub 	rax, PAGE_SIZE	;     size -= 4096;
	sub 	rcx, PAGE_SIZE	;     ptr  -= 4096;
	test 	byte [rcx], 0	;     *ptr;
	test	rax, rax		; }
	jg		.loop			; while (size > 0);

	pop 	rcx
	pop 	rax
	ret

__mingw_vfprintf:
	;; GMP calls into this for some reason even though it is a UCRT build and not MSVCRT build.
	jmp 	vfprintf
%else
_start:
	mov 	rdi, [rsp]		; argc
	lea 	rsi, [rsp + 8]	; argv
	call	main

	mov 	rdi, rax
	call	exit
%endif

__stack_chk_fail:
	jmp		abort

section .rdata

;; the value doesn't matter since I don't actually care that the stack security guard stuff works properly
__stack_chk_guard: dq 0x0000000000000000

%endif ;; %ifndef CRT_STUBS
