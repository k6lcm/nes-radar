ROM := nes_radar_scope_v3.nes
RC_ROM := nes_radar_select_pause_handshake_v1.nes
LEGACY_OUTPUT := nes_radar_0_3_rc2_candidate_v3.nes
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

all: $(RC_ROM)

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

$(RC_ROM): $(ROM)
	cp $(ROM) $(RC_ROM)

$(PRG_IMAGE) $(CHR_IMAGE): $(ROM) tools/split_cnrom.py | build
	$(PYTHON) tools/split_cnrom.py $(ROM) $(PRG_IMAGE) $(CHR_IMAGE)

hardware-images: $(PRG_IMAGE) $(CHR_IMAGE)

verify: $(ROM) $(RC_ROM) hardware-images
	test "$$(wc -c < $(ROM) | tr -d ' ')" = "65552"
	cmp $(ROM) $(RC_ROM)
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

clean:
	rm -rf build $(ROM) $(RC_ROM) $(LEGACY_OUTPUT)
