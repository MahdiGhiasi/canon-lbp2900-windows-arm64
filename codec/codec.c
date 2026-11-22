/* SPDX-License-Identifier: GPL-3.0-or-later
 * Small Windows entry point for captdriver's Hi-SCoA encoder. */
#include "hiscoa-compress.h"

__declspec(dllexport) size_t encode_band(void *output, size_t capacity,
        const void *pixels, unsigned stride, unsigned rows)
{
    return hiscoa_compress_band(output, capacity, pixels, stride, rows,
                                HISCOA_EOB_NORMAL, &hiscoa_default_params);
}
