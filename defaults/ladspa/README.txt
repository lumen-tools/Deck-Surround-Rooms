Fast Lookahead Limiter (swh LADSPA plugins)
===========================================

fast_lookahead_limiter_1913.so is the "Fast Lookahead limiter" (LADSPA ID 1913, label
fastLookaheadLimiter) from the swh LADSPA plugins by Steve Harris:
https://github.com/swh/ladspa (commit 0f54d2430febb4d5f02d13132dd91d7345e080b5).

It is licensed under the GNU General Public License, version 2 (see LICENSE-GPL-2.0.txt) and is
unmodified. DeckSurroundRooms loads it into the PipeWire filter chain as a separate plugin; the
BSD-3-Clause licence of the plugin code does not apply to this file.

The complete source is in src/:
  fast_lookahead_limiter_1913.xml   original source from the swh repository
  fast_lookahead_limiter_1913.c     generated from the XML with the repository's makestub.pl
  ladspa-util.h, ladspa.h           headers from the swh repository
  config.h                          minimal config for a standalone build (no translations)

Build (x86-64 Linux):
  cd src
  gcc -O2 -ffast-math -fPIC -shared -Wall -I. -o fast_lookahead_limiter_1913.so \
      fast_lookahead_limiter_1913.c -lm
  strip fast_lookahead_limiter_1913.so
