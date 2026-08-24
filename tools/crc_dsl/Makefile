# cross-platform
# requires mingw devkit on Windows

UNAME_S := $(shell uname -s)

GCC_ERRFLAGS := -Wdouble-promotion -Wauto-profile -Winvalid-pch -Wkeyword-macro -Wnull-dereference \
				-Wswitch-default -Wsuggest-attribute=returns_nonnull -Wanalyzer-symbol-too-complex \
				-Wmissing-variable-declarations -Wmissing-prototypes -Wduplicated-cond -Winit-self \
				-Werror -Wundef -Wextra -Winline -Wmissing-declarations -Walloc-zero -Wfloat-equal \
				-Wlogical-op -Wsuggest-attribute=cold -Wsuggest-attribute=format -Wredundant-decls \
				-Wformat-y2k -Wpadded -Wsuggest-attribute=const -Wunreachable-code -Wwrite-strings \
				-Wvector-operation-performance -Wzero-as-null-pointer-constant -Wstrict-prototypes \
				-Wunsuffixed-float-constants -Wstack-protector -Wvariadic-macros -Wsign-conversion \
				-Wflex-array-member-not-at-end -Wsuggest-attribute=malloc -Wsuggest-attribute=pure \
				-Wswitch-enum -Wnested-externs -Wtrivial-auto-var-init -Wunsafe-loop-optimizations \
				-Wstrict-flex-arrays -Winvalid-utf8 -Wdisabled-optimization -Wmissing-include-dirs \
				-Wmultichar -Wformat-nonliteral -Wformat-security -Wformat-signedness -Wconversion \
				-Wabi -Walloca -Wanalyzer-symbol-too-complex -Wanalyzer-too-complex -Wshadow -Wall \
				-Wsuggest-attribute=noreturn -Woverlength-strings -Warith-conversion -Wtrampolines \
				-Wsuggest-final-methods -Wopenacc-parallelism -fstrict-flex-arrays -Wunused-macros \
				-Wpointer-arith -Wcast-align -Wduplicated-branches -Wsuggest-final-types -Wpacked  \
				-Wbad-function-cast -Wdate-time

LD_LINUX ?= /lib64/ld-linux-x86-64.so.2

# -Wcast-align=strict
# -Waggregate-return

GCC_FLAGS	:=  -Ofast -nostdlib -fno-asynchronous-unwind-tables -fno-ident -fms-extensions \
				-flive-range-shrinkage -fipa-pta -fshort-enums -fweb -fwrapv -masm=intel -Iinclude

LD_FLAGS := -Ofast --fatal-warnings -Llib -L"$(shell dirname "$$(gcc -print-libgcc-file-name)")"

ifeq ($(UNAME_S),Windows_NT)
	LD_FLAGS	+= --warn-common --no-seh --exclude-all-symbols
	LD_LIBS		:= -lgcc -lgmp-win32 -lcryptbase -lkernel32 -lucrtbase
	NASM_FLAGS  := -fwin64 -DWINDOWS
else
	LD_FLAGS	+= -Ofast -Llib --fatal-warnings -dynamic-linker "$(LD_LINUX)"
	LD_LIBS		:= -lc -lgcc -lgmp
	NASM_FLAGS  := -felf64 -DLINUX
endif

# decide later on the following:
#   -fprefetch-loop-arrays
#   -fira-region=<one|all|mixed>

ifdef DEBUG
	GCC_FLAGS  += -g -DDEBUG=true
	NASM_FLAGS += -g
else
	LD_FLAGS   += -s
endif

ifeq ($(UNAME_S),Windows_NT)
main.exe: main.o crt-stubs.o
	ld $^ $(LD_FLAGS) $(LD_LIBS) -o $@
else
main: main.o crt-stubs.o
	ld $^ $(LD_FLAGS) $(LD_LIBS) -o $@
	chmod +x $@
	objcopy --remove-section=.eh_frame --remove-section=.eh_frame_hdr main main
endif

main.o: main.c $(wildcard include/*.h) Makefile
	gcc -c $< $(GCC_FLAGS) $(GCC_ERRFLAGS) -o $@

crt-stubs.o: crt-stubs.nasm Makefile
	nasm $(NASM_FLAGS) $< -o $@
ifndef DEBUG
	strip -S $@
endif

clean:
	rm -f *.o 2> /dev/null

distclean:
	rm -f *.o main main.exe 2> /dev/null
