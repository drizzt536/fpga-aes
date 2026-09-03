# cross-platform
# dependencies:
	# always: uname, dirname, strip, ld, rm, make, nasm >=3.0
	# Windows only: w64devkit (for GCC), Powershell Core
	# Linux only: GMP shared object, gcc, objcopy

UNAME_S := $(shell uname -s)

GCC_ERRFLAGS := -Wdouble-promotion -Wauto-profile -Winvalid-pch -Wkeyword-macro -Wnull-dereference \
				-Wswitch-default -Wsuggest-attribute=returns_nonnull -Wanalyzer-symbol-too-complex \
				-Wmissing-variable-declarations -Wmissing-prototypes -Wduplicated-cond -Winit-self \
				-Werror -Wundef -Wextra -Winline -Wmissing-declarations -Walloc-zero -Wfloat-equal \
				-Wlogical-op -Wsuggest-attribute=cold -Wsuggest-attribute=format -Wredundant-decls \
				-Wformat-y2k -Wpadded -Wsuggest-attribute=const -Wunreachable-code -Wwrite-strings \
				-Wvector-operation-performance -Wzero-as-null-pointer-constant -Wstrict-prototypes \
				-Wflex-array-member-not-at-end -Wsuggest-attribute=malloc -Wsuggest-attribute=pure \
				-Wswitch-enum -Wnested-externs -Wtrivial-auto-var-init -Wunsafe-loop-optimizations \
				-Wstrict-flex-arrays -Winvalid-utf8 -Wdisabled-optimization -Wmissing-include-dirs \
				-Wmultichar -Wformat-nonliteral -Wformat-security -Wformat-signedness -Wconversion \
				-Wabi -Walloca -Wanalyzer-symbol-too-complex -Wanalyzer-too-complex -Wshadow -Wall \
				-Wsuggest-attribute=noreturn -Woverlength-strings -Warith-conversion -Wtrampolines \
				-Wsuggest-final-methods -Wopenacc-parallelism -fstrict-flex-arrays -Wunused-macros \
				-Wpointer-arith -Wcast-align -Wduplicated-branches -Wsuggest-final-types -Wpacked  \
				-Wunsuffixed-float-constants -Wvariadic-macros -Wsign-conversion -Wdate-time       \
				-Wbad-function-cast -Wno-main

LD_LINUX ?= /lib64/ld-linux-x86-64.so.2

GCC_FLAGS	:=  -nostdlib -fno-asynchronous-unwind-tables -fno-ident -fms-extensions \
				-flive-range-shrinkage -fipa-pta -fshort-enums -fweb -fwrapv -masm=intel \
				-Iinclude
LD_FLAGS    :=  -Ofast -Llib -L"$(shell dirname "$$(gcc -print-libgcc-file-name)")"

# decide later on the following:
#   -fprefetch-loop-arrays
#   -fira-region=<one|all|mixed>

ifndef O
	O := fast
endif

ifneq ($O,g)
	# cachegrind needs the real prefixes to annotate properly.
	GCC_FLAGS += -ffile-prefix-map=include/=
endif

GCC_FLAGS += -O$O

ifeq ($(DEBUG),all)
	ifneq ($(UNAME_S),Windows_NT)
		# this stuff only works on Linux
		GCC_FLAGS += -fsanitize=address,undefined -fstack-protector-all
		LD_LIBS   += -lasan -lubsan  # -lasan has to come first
	endif

	DEBUG := extra
else
	# require __attribute__((stack_protect))
	GCC_FLAGS += -fstack-protector-explicit

	# libasan gives linker warnings
	LD_FLAGS  += --fatal-warnings
endif

ifeq ($(DEBUG),extra)
	GCC_FLAGS  += -g
	NASM_FLAGS += -g

	DEBUG := basic
else
	LD_FLAGS += -s
endif

ifeq ($(DEBUG),basic)
	# verbose logging
	GCC_FLAGS += -DDEBUG=true
endif

ifndef DEBUG
	DEBUG := off
endif

ifeq ($(UNAME_S),Windows_NT)
	LD_FLAGS	+= --warn-common --no-seh --exclude-all-symbols
	LD_LIBS		:= -lgcc -lgmp-win32 -lcryptbase -lkernel32 -lucrtbase
	NASM_FLAGS  := -fwin64 -DWINDOWS
else
	# Arch doesn't ship the static stuff with GMP, and I cannot be bothered to compile it myself
	# so I will just allow GMP's shared object to be a dependency on Linux.
	LD_FLAGS	+= -Ofast -Llib -dynamic-linker "$(LD_LINUX)"
	LD_LIBS		+= -lc -Bstatic -lgcc -Bdynamic -lgmp
	NASM_FLAGS  := -felf64 -DLINUX
endif

ifeq ($(UNAME_S),Windows_NT)
main.exe: main.o crt-stubs.o
	ld $^ $(LD_FLAGS) $(LD_LIBS) -o $@
else
main: main.o crt-stubs.o
	ld $^ $(LD_FLAGS) $(LD_LIBS) -o $@
	objcopy --remove-section=.eh_frame --remove-section=.eh_frame_hdr main main
endif

main.o: main.c $(wildcard include/*.h) Makefile
	gcc -c $< $(GCC_FLAGS) $(GCC_ERRFLAGS) -o $@

crt-stubs.o: crt-stubs.nasm Makefile
	nasm $(NASM_FLAGS) $< -o $@
ifneq ($(DEBUG),off)
	strip -S $@
endif

clean:
	@# TODO: figure out if there are other valgrind files.
	@#       then add them here, and to the gitignore.
	rm -f *.o cachegrind.out.* callgrind.out.* 2> /dev/null

distclean: clean
	rm -f main main.exe 2> /dev/null
