ROM := nes_radar_scope_v3.nes
OBJ := build/nes_radar_scope_v3.o
PRG_IMAGE := build/nes_radar_scope_v3.prg
CHR_IMAGE := build/nes_radar_scope_v3.chr
PYTHON ?= python3
METASPRITE_STAMP := build/metasprites.stamp
LDV_DIR := assets/ldv
LDV_ASSETS := $(LDV_DIR)/ldv_bg.chr $(LDV_DIR)/ldv_bg.nam \
	$(LDV_DIR)/ldv_bg.att $(LDV_DIR)/ldv_screen.inc
SPLASH_DIR := assets/splash
SPLASH_ASSETS := $(SPLASH_DIR)/splash_bg.chr $(SPLASH_DIR)/splash_bg.nam \
	$(SPLASH_DIR)/splash_bg.palette.bin

.PHONY: all assets hardware-images verify clean

all: $(ROM)

build:
	mkdir -p build

$(METASPRITE_STAMP): tools/generate_assets.py tools/generate_metasprites.py | build
	$(PYTHON) tools/generate_metasprites.py --output-dir build
	touch $@

assets: $(METASPRITE_STAMP) $(LDV_ASSETS) $(SPLASH_ASSETS)

$(OBJ): nes/nes_radar_scope_v3.s $(METASPRITE_STAMP) $(LDV_ASSETS) $(SPLASH_ASSETS) | build
	ca65 -g -I build -I $(LDV_DIR) -o $@ $<

$(ROM): $(OBJ) nes/cnrom256.cfg
	ld65 -C nes/cnrom256.cfg -o $@ -m build/nes_radar_scope_v3.map \
		--dbgfile build/nes_radar_scope_v3.dbg $<

$(PRG_IMAGE) $(CHR_IMAGE): $(ROM) tools/split_cnrom.py | build
	$(PYTHON) tools/split_cnrom.py $(ROM) $(PRG_IMAGE) $(CHR_IMAGE)

hardware-images: $(PRG_IMAGE) $(CHR_IMAGE)

# The reverse-channel transmit routine is cycle-timed and the bit period
# depends on its own linked address, because a delay loop straddling a page
# boundary would silently drop the baud rate from 9600 to 8170. Both
# verifiers run against the built ROM: verify_tx_timing charges the extra
# cycle a taken branch pays crossing a page and checks all 256 byte values,
# and verify_frame_bytes demodulates the ROM's own writes to $4016 and
# compares them against the server's request_bytes(), so the two sides catch
# each other disagreeing rather than restating a rule.
verify: $(ROM) hardware-images
	test "$$(wc -c < $(ROM) | tr -d ' ')" = "65552"
	printf 'NES\032\002\004\060\000' | cmp -n 8 - $(ROM)
	test "$$(wc -c < $(LDV_DIR)/ldv_bg.chr | tr -d ' ')" = "4096"
	test "$$(wc -c < $(LDV_DIR)/ldv_bg.nam | tr -d ' ')" = "960"
	test "$$(wc -c < $(LDV_DIR)/ldv_bg.att | tr -d ' ')" = "64"
	test "$$(wc -c < build/radar_sprites_16.chr | tr -d ' ')" = "4096"
	test "$$(wc -c < $(SPLASH_DIR)/splash_bg.chr | tr -d ' ')" = "4096"
	test "$$(wc -c < $(SPLASH_DIR)/splash_bg.nam | tr -d ' ')" = "1024"
	test "$$(wc -c < $(SPLASH_DIR)/splash_bg.palette.bin | tr -d ' ')" = "16"
	test "$$(wc -c < $(PRG_IMAGE) | tr -d ' ')" = "32768"
	test "$$(wc -c < $(CHR_IMAGE) | tr -d ' ')" = "32768"
	$(PYTHON) tools/verify_tx_timing.py $(ROM) build/nes_radar_scope_v3.dbg
	$(PYTHON) tools/verify_frame_bytes.py $(ROM) build/nes_radar_scope_v3.dbg

clean:
	rm -rf build $(ROM)
