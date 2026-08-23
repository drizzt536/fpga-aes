#pragma once
#define VA_IF_H

#ifndef VA_IF
	#define _VA_ID_IGNORED(...)
	#define _VA_ID(x...) x
	#define _VA_ID_IF(suffix, x...) _VA_ID ## suffix(x)
	#define VA_IF(t, f, ...) __VA_OPT__(t) _VA_ID_IF(__VA_OPT__(_IGNORED), f)
#endif
