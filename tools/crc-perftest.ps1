<#
.synopsis
	performance testing for the optimization stage of crc-gen.py
	for each algorithm, it stops after CSE takes at least 1 minute.
	it uses the default optimization settings (the lowest)

	requires awk
.parameter v
	verbosity level. passed directly to ./crc-gen.py. default is 1
.parameter sleep
	sleep time in seconds between each operation. default is 2
.parameter algorithm
	specify a specific algorithm to do instead of all of them.
	if not provided, or an empty string, all algorithms will be run.
.parameter trials
	number if trials to run for each algorithm/length combination.
	the CSE time is averaged between them. default is 2.
.parameter cutoff
	time in seconds. stop testing an algorithm once CSE takes at least `cutoff` seconds.
	default is 60 seconds.
.parameter redoAll
	if present, it perf tests all algorithms, even if the log file already exists.
.parameter listRemaining
	list the algorithms that have not been performance tested and exit.
#>
[cmdletbinding()]
param (
	[uint32] $v         = 1,
	[uint32] $sleep     = 2,
	[string] $algorithm = "",
	[uint32] $trials    = 2,
	[uint64] $cutoff    = 60,
	[switch] $help,
	[switch] $redoAll,
	[switch] $listRemaining
);

if ($help.isPresent) {
	get-help -full $MyInvocation.MyCommand.Source
	exit 0
}

if (-not (test-path -type container perflogs)) {
	# assumes there isn't a file named "perflogs"
	mkdir perflogs
}

$algorithms = $algorithm -eq "" -or $listRemaining.isPresent ?
	(./crc-gen.py -A | sls "(?<=^ - )\w+$").matches.value :
	@($algorithm)

if ($listRemaining) {
	foreach ($alg in $algorithms) {
		if (-not (test-path -type leaf "./perflogs/$alg.log")) {
			echo $alg
		}
	}

	exit 0
}

if (-not (gcm -type app -ea ignore awk)) {
	write-host "`e[31mrequired program 'awk' was not found"
	exit 1
}

$cutoff *= 1000000000ul # change from seconds to nanoseconds

function wait {
	write-host "sleeping ${sleep}s" -noNewline
	start-sleep -s $sleep
	write-host "`r`e[K" -noNewline
}

foreach ($alg in $algorithms) {
	cls

	$logfile = "./perflogs/$alg.log"
	$tmpfile = "./perflogs/$alg.tmp"

	if (-not $redoAll.isPresent -and (test-path -type leaf $logfile)) {
		continue
	}

	$data = [Collections.ArrayList]::new()
	$len  = 1

	do {
		# clear the screen but preserve the scroll buffer
		write-host "`e[H`e[2Jnext: alg=$alg len=$len"
		$data | format-table

		$elem = $null

		for ($i = 1; $i -le $trials; $i++) {
			wait
			write-host "running trial $i/$trials"
			$tmp = ./crc-gen.py -a $alg -l $len -cv $v -fm | convertfrom-json

			if ($elem -eq $null) {
				$elem = $tmp
			}
			else {
				$elem.cse_time_ns += $tmp.cse_time_ns
				$elem.gen_time_ns += $tmp.gen_time_ns
			}
		}

		$elem.cse_time_ns = [int64] ($elem.cse_time_ns / $trials)
		$elem.gen_time_ns = [int64] ($elem.gen_time_ns / $trials)


		$elem.compression *= 100 # convert to percentage
		[void] $data.add($elem)

		$len = $len -shl 1
	} while ($elem.cse_time_ns -lt $cutoff)

	$data | format-table > $tmpfile
	awk '$0 && !/^-/' $tmpfile > $logfile
	rm $tmpfile
}

write-host "`e[1;32mdone"
exit 0
