# you only need to do this on Windows.
# On Linux, just install GMP system-wide with pacman or apt or whatever.

if (-not (test-path -type container lib)) {
	[void] (mkdir lib)
}

if (-not $isWindows) {
	write-host "setup-libs.ps1 is only needed on Windows"
	exit 0
}

if (-not (test-path -type leaf lib/libgmp-win32.a)) {
	write-host "setting up libgmp"
	$repo = "https://mirror.msys2.org/mingw/ucrt64/"
	$pkg  = "mingw-w64-ucrt-x86_64-gmp"
	$kind = "any"

	$version = (
		(
			(invoke-webrequest $repo).links.outerHtml
			| sls "$pkg-(.+?)-$kind\.pkg\.tar\.zst(?=`")"
		).matches
		| % { $_.groups[1].value }
		| sort { [version] ($_ -replace '-', '.') }
		| select -last 1
	)

	write-host "downloading GMP v$version"
	$file = "$pkg-$version-$kind.pkg.tar.zst"

	wget "$repo$file"

	# bsdtar
	tar -xf $file --strip-components=1 ucrt64/include/gmp.h ucrt64/lib/libgmp.a
	rm $file
	mv -force lib/libgmp.a lib/libgmp-win32.a
	objcopy -R '.rdata$zzz' lib/libgmp-win32.a # remove ident nonsense
}
else {
	write-host "libgmp is already set up"
}

if (-not (test-path -type leaf lib/libgcc-win32.a)) {
	write-host "setting up libgcc"
	cp $(gcc -print-libgcc-file-name) lib/libgcc-win32.a
	objcopy -R '.rdata$zzz' lib/libgcc-win32.a # remove ident nonsense
}
else {
	write-host "libgcc is already set up"
}

if (-not (test-path -type leaf lib/libc-win32.a)) {
	write-host "setting up libc"
	cp $(ld -t -lucrtbase -o NUL 2> NUL | grep libucrtbase) lib/libc-win32.a
	objcopy -R '.rdata$zzz' lib/libc-win32.a # remove ident nonsense
}
else {
	write-host "libc is already set up"
}

exit 0
