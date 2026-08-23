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
