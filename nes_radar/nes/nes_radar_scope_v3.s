; NES Radar Scope v2 -- LDV display layer
;
; Starts with a controller-1 ICAO editor, reports the selected four-letter code
; through controller-port-2 OUT0, then receives radar data through port-2 D0 at
; the Milestone 005-proven 9600-baud timing. The complete receive primitive is
; unchanged; controller 1 is sampled only after complete bytes.

.setcpu "6502"

PPUCTRL   = $2000
PPUMASK   = $2001
PPUSTATUS = $2002
OAMADDR   = $2003
PPUSCROLL = $2005
PPUADDR   = $2006
PPUDATA   = $2007
OAMDMA    = $4014
JOY1      = $4016
JOY2      = $4017
DMC_FREQ  = $4010
APUSTATUS = $4015

MARKER            = $A5
PACKET_TYPE_SCENE = $01
PACKET_TYPE_IDENTITY = $02
PACKET_TYPE_LOCATION = $03
PROTOCOL_VERSION  = $02
MAX_TARGETS       = 8
RECORD_SIZE       = 9
IDENTITY_RECORD_SIZE = 25
MAX_PAYLOAD       = 200

SCENE_STALE       = $01
SCENE_SEVERE      = $1C
TRACK_INVALID     = $08
ALT_INVALID       = $10
SPEED_INVALID     = $20
TARGET_ALERT      = $40

PPUCTRL_SPR_8X16  = %00100000
PPUCTRL_UPDATE_NMI = %10100000
SHOW_SCOPE        = %00011110
SHOW_BACKGROUND   = %00001010
SHOW_STARTUP      = %00011110

CHAR_SPACE        = 0
CHAR_0            = 1
CHAR_A            = 11
CHAR_PLUS         = 37
CHAR_HYPHEN       = 38
CHAR_DOT          = 39
CHAR_SLASH        = 40
CHAR_COLON        = 41

STARTUP_CODE_ADDR   = $218E      ; row 12, column 14
STARTUP_CURSOR_ADDR = $21AE      ; row 13, column 14
STARTUP_MESSAGE_ADDR = $21E8     ; row 15, column 8
STARTUP_SPRITE_Y    = 12 * 8 - 1
STARTUP_SPRITE_X    = 14 * 8
STARTUP_SPRITE_PALETTE = 2

SCOPE_ORIGIN_X    = 56
SCOPE_ORIGIN_Y    = 24
SCOPE_LOCAL_LIMIT = 144
META_CENTRE_X     = 7
META_CENTRE_Y     = 7
META_LDV_OFFSET_X_LEFT  = SCOPE_ORIGIN_X - META_CENTRE_X
META_LDV_OFFSET_X_RIGHT = META_LDV_OFFSET_X_LEFT + 8
META_LDV_OFFSET_Y       = SCOPE_ORIGIN_Y - META_CENTRE_Y - 1

SEL_TGT  = 0
SEL_TYPE = 2
SEL_REG  = 6
SEL_SQWK = 12
SEL_CAT  = 16
SEL_ALT  = 18
SEL_SPD  = 23
SEL_TRK  = 26
SEL_VS   = 29
SEL_DIST = 34

STATUS_COUNT = 0
STATUS_APT   = 2
STATUS_LINK  = 6
LINK_STATE_WIDTH = 9
STATUS_SIZE       = STATUS_LINK + LINK_STATE_WIDTH

BUTTON_A          = $80
BUTTON_B          = $40
BUTTON_SELECT     = $20
BUTTON_START      = $10
BUTTON_UP         = $08
BUTTON_DOWN       = $04
BUTTON_LEFT       = $02
BUTTON_RIGHT      = $01
OUT0_REQUEST_MARKER = $4E
OUT0_CHECK_SEED   = $A5

; Reverse channel, NES to host.
;
; 9,600 8N1 bit-banged on OUT0 and read as ordinary UART data on the host's
; RXD. OUT0 high is mark, low is space, so no inverter is needed; the ROM
; rests OUT0 low, which the host sees as one break byte at each edge of a
; burst. Both requests are six bytes: marker, four payload bytes, and an
; XOR checksum seeded with $A5. See tools/verify_frame_bytes.py and
; ../SIGNALING.md.

; The pause request is a six-byte UART frame with its own marker, padded to
; the same length as a location request so both share one length and one
; checksum rule. A zero payload can never collide with a location request
; because the editor only ever emits A-Z.
PAUSE_REQUEST_MARKER = $50
UART_FRAME_BYTES     = 6
UART_GUARD_UNITS     = 8          ; 800 us of mark before the first start bit
; Shortened from 448 when chunked reception arrived. The window used to be the
; only time the controller did anything, so it wanted to be long. Now the pad
; also works between chunks, and the time is needed for the chunk gaps instead.
DISPLAY_WINDOW_FRAMES = 360       ; 6.00 seconds at NTSC field rate

; The host holds a long quiet gap after every CHUNK_BYTES bytes of a packet.
; That gap is the only moment inside a packet with room to wait for vblank and
; repaint, so it is where the selection is serviced. Both sides count the
; marker as byte 1 and must agree on this number: the server's --chunk-bytes
; defaults to the same 8. A mismatch is loud rather than silent, since the ROM
; would spend a gap that is not there and lose the next byte to a CRC failure.
CHUNK_BYTES = 8
LINK_STALE_FRAMES     = 600       ; 10 seconds without a valid packet
SPLASH_FRAMES         = 120       ; about two seconds at NTSC field rate
CHR_BANK_SPLASH       = 0
CHR_BANK_RADAR        = 1

; Splash name and version stamp.  The splash bank is a bitmap of the LDV logo
; and has no font, so the glyphs are copied out of the LDV font into the tiles it
; leaves unused at the top of the bank (see the CHR0 segment).  Digits are
; contiguous, so VER_0 + n is the tile for digit n.  Tile $00 is blank in this
; bank, which makes it the space.
VER_GLYPH_BASE        = $E6
VER_GLYPH_COUNT       = 18        ; ten digits, '.', 'V', then N E S R A D
VER_0                 = VER_GLYPH_BASE
VER_DOT               = VER_GLYPH_BASE + 10
VER_V                 = VER_GLYPH_BASE + 11
VER_N                 = VER_GLYPH_BASE + 12
VER_E                 = VER_GLYPH_BASE + 13
VER_S                 = VER_GLYPH_BASE + 14
VER_R                 = VER_GLYPH_BASE + 15
VER_A                 = VER_GLYPH_BASE + 16
VER_D                 = VER_GLYPH_BASE + 17
VER_SPACE             = $00
SPLASH_TITLE_ADDR     = $232C     ; row 25, column 12
VERSION_STAMP_ADDR    = $236D     ; row 27, column 13 -- one blank row below

.include "ldv_screen.inc"
.include "assets_metasprite.inc"

.segment "ZEROPAGE"
received:       .res 1
crc_hi:         .res 1
crc_lo:         .res 1
received_hi:    .res 1
received_lo:    .res 1
packet_seq:     .res 1
packet_type:    .res 1
packet_flags:   .res 1
packet_count:   .res 1
packet_length:  .res 1
have_seq:       .res 1
last_seq:       .res 1
expected_seq:   .res 1
temp:           .res 1
record_flags:   .res 1
slot_number:    .res 1
records_left:   .res 1
seen_slots:     .res 1
error_code:     .res 1
panel_offset:   .res 1
value_lo:       .res 1
value_hi:       .res 1
digit_hundreds: .res 1
digit_tens:     .res 1
digit_ones:     .res 1
rec_offset:     .res 1
meta_left:      .res 1
meta_right:     .res 1
vblank_ready:   .res 1
controller_current: .res 1
controller_previous: .res 1
controller_pressed: .res 1
controller_pending: .res 1
editor_index:   .res 1
startup_error:  .res 1
; Two reserved zero-page bytes. They preserve the zero-page layout of the
; hardware-accepted ROM so the built .nes file stays bit-identical.
_reserved0:     .res 1
_reserved1:     .res 1
delay_blocks:   .res 1
field_src:      .res 2
field_width:    .res 1
field_font:     .res 1
field_addr_hi:  .res 1
field_addr_lo:  .res 1
active_slots:   .res 1
selected_slot:  .res 1
previous_selected_slot: .res 1
oam_rotation:   .res 1
track_value:    .res 1
table_slot_index: .res 1
table_rows_left: .res 1
identity_offset: .res 1
displayed_count: .res 1
display_frames_lo: .res 1
display_frames_hi: .res 1
link_age_lo:     .res 1
link_age_hi:     .res 1
link_timed_out:  .res 1
link_data_stale: .res 1
navigation_requested: .res 1
pause_waiting:        .res 1
; Reverse-UART transmit scratch.
tx_byte:              .res 1
tx_index:             .res 1
chunk_count:          .res 1
pad_commit_pending:   .res 1

.segment "BSS"
.align 256
oam_shadow:     .res 256
sample_port1:   .res 1
sample_port2:   .res 1
scene_payload:  .res MAX_PAYLOAD
identity_tiles: .res 192
icao_code:      .res 4
selected_fields: .res 37
status_fields:   .res STATUS_SIZE
startup_cursor:  .res 4
splash_frames:   .res 1
; Reverse-UART frame in transmission order: marker, four payload bytes, XOR
; checksum. Assembled here rather than sent on the fly because uart_tx_byte
; destroys every register and cannot host a loop counter.
uart_frame:      .res UART_FRAME_BYTES

.segment "HEADER"
    .byte "NES", $1A
    .byte 2                       ; 32 KiB fixed PRG
    .byte 4                       ; four 8 KiB CHR-ROM banks
    .byte $30, $00                ; mapper 3 CN-ROM, horizontal mirroring
    .res 8, $00

.segment "CODE"

.proc reset
    sei
    cld
    ldx #$40
    stx JOY2
    ldx #$FF
    txs
    inx
    stx PPUCTRL
    stx PPUMASK
    stx DMC_FREQ
    stx APUSTATUS

    bit PPUSTATUS
@wait_vblank_1:
    bit PPUSTATUS
    bpl @wait_vblank_1
@wait_vblank_2:
    bit PPUSTATUS
    bpl @wait_vblank_2

    lda #'K'
    sta icao_code
    lda #'S'
    sta icao_code + 1
    lda #'B'
    sta icao_code + 2
    lda #'A'
    sta icao_code + 3
    lda #0
    sta have_seq
    sta startup_error
    sta active_slots
    sta selected_slot
    sta previous_selected_slot
    sta oam_rotation
    sta controller_pending
    sta displayed_count
    sta link_age_lo
    sta link_age_hi
    sta link_timed_out
    sta navigation_requested
    sta pause_waiting
    lda #1
    sta link_data_stale
    jsr initialize_display_buffers
    jsr initialize_splash_video
    jsr wait_splash

@show_editor:
    jsr initialize_startup_video
    lda #0
    sta editor_index
    sta controller_previous
    sta navigation_requested
    sta pause_waiting
    jsr render_editor
    lda startup_error
    beq @editor_loop
    lda #1
    jsr show_startup_message

@editor_loop:
    jsr wait_vblank
    jsr read_controller
    lda controller_previous
    eor #$FF
    and controller_current
    sta controller_pressed
    lda controller_current
    sta controller_previous

    lda controller_pressed
    and #BUTTON_START
    bne @submit_icao
    lda controller_pressed
    and #BUTTON_UP
    bne @letter_up
    lda controller_pressed
    and #BUTTON_DOWN
    bne @letter_down
    lda controller_pressed
    and #(BUTTON_RIGHT | BUTTON_A)
    bne @move_right
    lda controller_pressed
    and #(BUTTON_LEFT | BUTTON_B)
    bne @move_left
    jmp @editor_loop

@letter_up:
    ldx editor_index
    lda icao_code,x
    cmp #'Z'
    bne :+
    lda #'A' - 1
:
    clc
    adc #1
    sta icao_code,x
    jmp @editor_changed

@letter_down:
    ldx editor_index
    lda icao_code,x
    cmp #'A'
    bne :+
    lda #'Z' + 1
:
    sec
    sbc #1
    sta icao_code,x
    jmp @editor_changed

@move_right:
    inc editor_index
    lda editor_index
    and #$03
    sta editor_index
    jmp @editor_changed

@move_left:
    lda editor_index
    bne :+
    lda #4
    sta editor_index
:
    dec editor_index

@editor_changed:
    lda #0
    sta startup_error
    jsr render_editor
    jmp @editor_loop

@submit_icao:
    lda #0
    jsr show_startup_message
    jsr send_location_request
    lda #0
    sta have_seq

@seek_marker:
    jsr receive_marker_byte_with_idle
    ; Keep the received marker and framing carry intact until both are checked.
    ; Both flags are strictly 0/1, so BIT preserves the marker and carry.
    bit navigation_requested
    beq :+
    bit pause_waiting
    bne :+
    jmp @request_navigation_pause
:
    bcc :+
    jmp @framing_error
:
    cmp #MARKER
    bne @seek_marker               ; harmless noise before a marker

    ; The marker is byte 1 of the packet and does not come through
    ; receive_byte_with_controller, so seed the count rather than zero it.
    lda #1
    sta chunk_count

    lda #$FF
    sta crc_hi
    sta crc_lo

    jsr receive_and_crc
    bcc :+
    jmp @framing_error
:
    sta packet_type
    cmp #PACKET_TYPE_SCENE
    beq :+
    cmp #PACKET_TYPE_IDENTITY
    beq :+
    cmp #PACKET_TYPE_LOCATION
    beq :+
    jmp @header_error
:

    jsr receive_and_crc
    bcs @framing_error
    cmp #PROTOCOL_VERSION
    bne @header_error

    jsr receive_and_crc
    bcs @framing_error
    sta packet_seq

    jsr receive_and_crc
    bcs @framing_error
    sta packet_flags

    jsr receive_and_crc
    bcs @framing_error
    sta packet_count

    jsr receive_and_crc
    bcs @framing_error
    sta packet_length

    lda packet_type
    cmp #PACKET_TYPE_SCENE
    bne @non_scene_header
    lda packet_flags
    and #$E0
    bne @header_error
    lda packet_count
    cmp #MAX_TARGETS + 1
    bcs @header_error
    sta temp
    asl a
    asl a
    asl a                          ; count * 8
    clc
    adc temp                       ; count * 9
    cmp packet_length
    bne @header_error
    jmp @payload_start

@non_scene_header:
    cmp #PACKET_TYPE_IDENTITY
    beq @identity_header
    lda packet_flags
    and #$FE
    bne @header_error
    lda packet_count
    cmp #1
    bne @header_error
    lda packet_length
    cmp #4
    bne @header_error
    jmp @payload_start

@identity_header:
    lda packet_flags
    bne @header_error
    lda packet_count
    cmp #MAX_TARGETS + 1
    bcs @header_error
    sta temp
    asl a
    asl a
    asl a                          ; count * 8
    sta record_flags
    asl a                          ; count * 16
    clc
    adc record_flags               ; count * 24
    clc
    adc temp                       ; count * 25
    cmp packet_length
    bne @header_error
    jmp @payload_start

@framing_error:
    lda #1                         ; UART stop-bit/framing failure
    jsr show_error
    jmp @seek_marker

@header_error:
    lda #2                         ; type/version/flags/count/length
    jsr show_error
    jmp @seek_marker

@payload_start:
    ldy #0
@payload_byte:
    cpy packet_length
    beq @payload_done
    jsr receive_and_crc
    bcs @framing_error
    sta scene_payload,y
    iny
    bne @payload_byte

@payload_done:
    jsr receive_byte_with_controller
    bcs @framing_error
    sta received_hi
    jsr receive_byte_with_controller
    bcs @framing_error
    sta received_lo
    lda received_hi
    cmp crc_hi
    bne @crc_error
    lda received_lo
    cmp crc_lo
    bne @crc_error
    jsr note_valid_packet

    lda packet_type
    cmp #PACKET_TYPE_LOCATION
    beq @location_payload
    cmp #PACKET_TYPE_IDENTITY
    beq @identity_payload
    jsr validate_records
    bcs @record_error
    jmp @records_valid

@identity_payload:
    jsr validate_identity_records
    bcs @record_error
    lda packet_count
    bne @identity_records
    jsr service_control_heartbeat
    lda navigation_requested
    beq @heartbeat_done
    lda pause_waiting
    beq @heartbeat_done
    jmp @return_to_editor
@heartbeat_done:
    jmp @seek_marker
@identity_records:
    jsr apply_identity_records
    jsr build_selected_identity
    jmp @seek_marker

@location_payload:
    ldx #0
@location_character:
    lda scene_payload,x
    cmp #'A'
    bcc @record_error
    cmp #'Z' + 1
    bcs @record_error
    cmp icao_code,x
    bne @record_error
    inx
    cpx #4
    bne @location_character
    lda packet_flags
    and #1
    beq @location_valid
    lda #1
    sta startup_error
    jmp @show_editor
@location_valid:
    jsr initialize_display_buffers
    jsr initialize_video
    lda #0
    sta have_seq
    jmp @seek_marker

@crc_error:
    lda #3                         ; CRC-16 mismatch
    jsr show_error
    jmp @seek_marker

@record_error:
    lda #4                         ; scene/identity record or location-result mismatch
    jsr show_error
    jmp @seek_marker

@records_valid:
    lda have_seq
    beq @accept
    lda packet_seq
    cmp last_seq
    bne :+
    jmp @seek_marker               ; exact duplicate: no display change
:
    cmp expected_seq
    beq @accept

    ; Reject the gap scene, but establish a recovery point. The next
    ; sequential scene can be accepted instead of latching an error forever.
    lda packet_seq
    sta last_seq
    clc
    adc #1
    sta expected_seq
    lda #5                         ; sequence gap/out-of-order scene
    jsr show_error
    jmp @seek_marker

@accept:
    lda packet_seq
    sta last_seq
    clc
    adc #1
    sta expected_seq
    lda #1
    sta have_seq

    lda seen_slots
    sta active_slots
    lda packet_count
    sta displayed_count
    jsr update_selection
    jsr build_oam_shadow
    jsr build_selected_fields
    jsr build_status_fields
    lda #0
    sta link_data_stale
    lda packet_flags
    and #SCENE_STALE
    beq :+
    lda #1
    sta link_data_stale
    sta link_timed_out             ; already visibly WAITING; do not re-fire
    jsr set_link_waiting
    jsr forget_scene_sequence
:
    lda packet_flags
    and #SCENE_SEVERE
    beq :+
    lda #1
    sta link_data_stale
    jsr set_link_error
:
    jsr commit_display
    inc oam_rotation
    lda oam_rotation
    and #7
    sta oam_rotation
    jsr animate_display_window
    lda navigation_requested
    bne :+
    jmp @seek_marker
:
    lda pause_waiting
    beq @request_navigation_pause
    jmp @seek_marker

@request_navigation_pause:
    lda #1
    sta pause_waiting
    jsr send_pause_request
    jmp @seek_marker

@return_to_editor:
    lda #0
    sta navigation_requested
    sta pause_waiting
    sta have_seq
    sta active_slots
    sta controller_pending
    sta startup_error
    jmp @show_editor
.endproc

; Receive one byte and fold it into CRC-16/CCITT-FALSE. Returns the original
; byte in A. Carry preserves the framing-error convention from receive_byte.
.proc receive_and_crc
    jsr receive_byte_with_controller
    bcs @error
    sta temp
    jsr crc16_update
    lda temp
    clc
@error:
    rts
.endproc

; CRC-16/CCITT-FALSE: polynomial $1021, initial $FFFF, MSB first, no final XOR.
; A is the next byte and crc_hi:crc_lo is the running value.
.proc crc16_update
    eor crc_hi
    sta crc_hi
    ldx #8
@bit:
    asl crc_lo
    rol crc_hi
    bcc @next
    lda crc_hi
    eor #$10
    sta crc_hi
    lda crc_lo
    eor #$21
    sta crc_lo
@next:
    dex
    bne @bit
    rts
.endproc

; Returns the received byte in A/received with carry clear. Carry set means an
; invalid LOW stop sample. This is kept cycle-for-cycle with Milestone 005.
.proc receive_byte
@seek_high:
    jsr sample_line
    beq @seek_high
@wait_start:
    jsr sample_line
    bne @wait_start

    lda #$00
    sta received
    jsr delay_start_to_bit0

    .repeat 7
        jsr sample_line
        cmp #1
        ror received
        jsr delay_between_samples
    .endrepeat

    jsr sample_line
    cmp #1
    ror received
    jsr delay_between_samples

    jsr sample_line
    beq @framing_error
    lda received
    clc
    rts
@framing_error:
    sec
    rts
.endproc

; The host leaves a 5 ms guard after every byte. Use that already-provisioned
; quiet interval to scan controller 1 and latch edges, while leaving the
; hardware-proven receive_byte and its cycle timing completely unchanged.
.proc receive_byte_with_controller
    jsr receive_byte
    php
    pha
    txa
    pha
    tya
    pha
    jsr latch_controller
    ; Every packet byte after the marker arrives here, so this is where the
    ; chunk boundary falls. receive_byte is not touched: the gap is found by
    ; counting bytes, not by timing the line, which keeps the cycle-counted
    ; sampling path exactly as it was proven.
    inc chunk_count
    lda chunk_count
    cmp #CHUNK_BYTES
    bne :+
    lda #0
    sta chunk_count
    jsr chunk_service
:
    pla
    tay
    pla
    tax
    pla
    plp
    rts
.endproc

; Service the pad inside a chunk gap. The host guarantees about 30 ms here and
; the worst case below is a vblank wait of one frame plus the write, near 18 ms.
;
; Select is deliberately left pending. Its owner is the display window or the
; link timeout, and handing a pause request to the middle of a packet would
; start a reverse transmission while the host is still sending.
.proc chunk_service
    ; The caller latched the pad immediately before this, so do not latch again.
    lda controller_pending
    and #(BUTTON_UP | BUTTON_DOWN | BUTTON_LEFT | BUTTON_RIGHT)
    sta controller_pressed
    beq @carry_over                ; nothing new, but a prepared panel may wait
    eor #$FF
    and controller_pending
    sta controller_pending
    jsr move_selection
    jsr build_selected_fields
    jmp @commit
@carry_over:
    ; A press picked up during the marker wait can arrive with its panel built
    ; and no vblank spent yet. The gap is a better place to finish it than the
    ; hunt, so take it here rather than leaving the screen a frame behind.
    lda pad_commit_pending
    beq @done
@commit:
    lda #0
    sta pad_commit_pending
    ; The gap is long enough to wait for vblank properly, unlike the hunt.
    jsr commit_selection
@done:
    rts
.endproc

; Wait for the next packet marker while keeping Select and link age responsive.
; The once-per-vblank hook replaces the rejected continuous controller scan.
; Once a LOW start bit is found, the calibrated sampling sequence below is
; identical to receive_byte; every remaining byte still uses receive_byte.
.proc receive_marker_byte_with_idle
@seek_high:
    jsr sample_line
    bne @wait_start
    jsr service_idle_if_vblank
    lda navigation_requested
    beq @seek_high
    lda pause_waiting
    beq @cancel
    jmp @seek_high
@wait_start:
    jsr sample_line
    beq @start
    jsr service_idle_if_vblank
    lda navigation_requested
    beq @wait_start
    lda pause_waiting
    beq @cancel
    jmp @wait_start

@start:
    lda #$00
    sta received
    jsr delay_start_to_bit0

    .repeat 7
        jsr sample_line
        cmp #1
        ror received
        jsr delay_between_samples
    .endrepeat

    jsr sample_line
    cmp #1
    ror received
    jsr delay_between_samples

    jsr sample_line
    beq @framing_error
    lda received
    clc
    rts
@framing_error:
@cancel:
    sec
    rts
.endproc

; PPUSTATUS is sampled only while the serial input is HIGH/idle. Work is done
; at most once per video field. This runs both during the post-scene display
; window and during the between-packet idle after the window has expired; the
; chunk gaps inside a packet are handled by their own service point.
.proc service_idle_if_vblank
    bit PPUSTATUS
    bpl @prepare_pad
    ; --- inside vblank ---
    ; The write goes first so only the roughly 84 cycles of polling latency sit
    ; ahead of it. latch_controller and age_link are RAM work and can safely
    ; run past the end of vblank.
    lda pad_commit_pending
    beq @no_commit
    lda #0
    sta pad_commit_pending
    jsr commit_selection_fields
@no_commit:
    jsr latch_controller
    jsr age_link
    bcc @navigation
    ; The timeout is a one-shot transition after prolonged silence. Refresh
    ; all four dynamic frames so no old aircraft remains visible.
    jsr commit_display
@navigation:
    ; During an active stream, update_selection consumes a pending Select only
    ; after the next scene, at the beginning of a guaranteed quiet window. If
    ; the link has already timed out, no old stream owns D0, so allow recovery.
    lda link_timed_out
    beq @done
    lda controller_pending
    and #BUTTON_SELECT
    beq @done
    lda #1
    sta navigation_requested
    lda controller_pending
    and #($FF - BUTTON_SELECT)
    sta controller_pending
@done:
    rts

    ; --- outside vblank ---
    ; Marker-wait responsiveness. Before this the pad was latched here but
    ; never acted on, so the scope ignored it for the whole gap between the
    ; display window and the packet, which is one to three seconds.
    ;
    ; Only the RAM half runs here. build_selected_fields alone is well over a
    ; thousand cycles, including a 45-iteration multiply, and putting it inside
    ; vblank would overrun into rendering and produce garbage tiles. The write
    ; waits for the next vblank, one frame later.
    ;
    ; This costs sampling blindness while it runs, so it is gated on an actual
    ; press. A held direction produces one edge, not a stream, so the exposure
    ; is one burst per press rather than one per frame.
@prepare_pad:
    lda pad_commit_pending
    bne @done
    lda controller_pending
    and #(BUTTON_UP | BUTTON_DOWN | BUTTON_LEFT | BUTTON_RIGHT)
    sta controller_pressed
    beq @done
    eor #$FF
    and controller_pending
    sta controller_pending
    jsr move_selection
    jsr build_selected_fields
    lda #1
    sta pad_commit_pending
    ; Throw away a vblank that began while the work above was running. Without
    ; this the next poll sees the flag set and commits, but the flag says only
    ; that vblank started at some point during those two thousand cycles, not
    ; that it started recently. Committing near the end of vblank overruns into
    ; rendering, and a $2007 write during rendering lands wherever v has
    ; drifted, so it scribbles the nametable rather than failing cleanly. That
    ; is what destroyed the scope background and produced bursts of garbage.
    ;
    ; Discarding it costs one frame of latency on the repaint and makes the
    ; poll's 84-cycle bound the real bound.
    bit PPUSTATUS
    rts
.endproc

.proc sample_line
    ldx #1
    stx JOY1
    dex
    stx JOY1
    pha
    pla
    lda JOY1
    sta sample_port1,x
    lda JOY2
    sta sample_port2,x
    lda sample_port2
    and #$01
    eor #$01
    rts
.endproc

.proc delay_start_to_bit0
    .repeat 102
        nop
    .endrepeat
    rts
.endproc

.proc delay_between_samples
    .repeat 55
        nop
    .endrepeat
    rts
.endproc

; Check reserved target flags, coordinate bounds, and unique stable slots.
; Carry set reports malformed data without changing the displayed scene.
.proc validate_records
    lda #0
    sta seen_slots
    lda packet_count
    sta records_left
    ldy #0
@record:
    lda records_left
    beq @valid
    lda scene_payload,y
    bmi @invalid
    and #$07
    tax
    lda slot_masks,x
    and seen_slots
    bne @invalid
    lda slot_masks,x
    ora seen_slots
    sta seen_slots
    lda scene_payload + 1,y
    cmp #160
    bcs @invalid
    lda scene_payload + 2,y
    cmp #160
    bcs @invalid
    lda scene_payload + 7,y
    cmp #$80                        ; unavailable is valid
    beq @rate_valid
    cmp #100                        ; +0 through +99
    bcc @rate_valid
    cmp #$9D                        ; $9D through $FF = -99 through -1
    bcc @invalid
@rate_valid:
    lda scene_payload + 8,y
    cmp #$FF                        ; unavailable is valid
    beq @distance_valid
    cmp #100                        ; 0.0 through 9.9 n.m.
    bcs @invalid
@distance_valid:
    tya
    clc
    adc #RECORD_SIZE
    tay
    dec records_left
    bne @record
@valid:
    clc
    rts
@invalid:
    sec
    rts
.endproc

; Validate SLOT,CALLSIGN[8],TYPE[4],REG[6],SQWK[4],CAT[2] records. Identity
; bytes are uppercase ASCII letters, digits, spaces, or hyphens. Carry set
; reports malformed data without changing the displayed identity table.
.proc validate_identity_records
    lda #0
    sta seen_slots
    lda packet_count
    sta records_left
    ldy #0
@record:
    lda records_left
    beq @valid
    lda scene_payload,y
    cmp #MAX_TARGETS
    bcs @invalid
    tax
    lda slot_masks,x
    and seen_slots
    bne @invalid
    lda slot_masks,x
    ora seen_slots
    sta seen_slots
    iny
    lda #24
    sta temp
@character:
    lda scene_payload,y
    jsr validate_identity_char
    bcs @invalid
    iny
    dec temp
    bne @character
    dec records_left
    bne @record
@valid:
    clc
    rts
@invalid:
    sec
    rts
.endproc

.proc validate_identity_char
    cmp #' '
    beq @valid
    cmp #'-'
    beq @valid
    cmp #'0'
    bcc @invalid
    cmp #':'
    bcc @valid
    cmp #'A'
    bcc @invalid
    cmp #'['
    bcs @invalid
@valid:
    clc
    rts
@invalid:
    sec
    rts
.endproc

; Translate a validated identity packet into LDV character indices. Each slot
; owns 24 characters: callsign, type, registration, squawk, and category.
.proc apply_identity_records
    lda packet_count
    sta records_left
    ldy #0
@record:
    lda records_left
    beq @done
    lda scene_payload,y
    sta slot_number
    lda slot_number
    asl a
    asl a
    asl a                           ; slot * 8
    sta panel_offset
    asl a                           ; slot * 16
    clc
    adc panel_offset                ; slot * 24
    tax
    iny
    lda #24
    sta temp
@character:
    lda scene_payload,y
    jsr identity_char_tile
    sta identity_tiles,x
    inx
    iny
    dec temp
    bne @character
    dec records_left
    bne @record
@done:
    rts
.endproc

.proc identity_char_tile
    cmp #' '
    bne :+
    lda #CHAR_SPACE
    rts
:
    cmp #'-'
    bne :+
    lda #CHAR_HYPHEN
    rts
:
    cmp #'A'
    bcs @letter
    sec
    sbc #'0'
    clc
    adc #CHAR_0
    rts
@letter:
    sec
    sbc #'A'
    clc
    adc #CHAR_A
    rts
.endproc

; Translate validated scene records into the first sixteen OAM entries. Each
; stable slot owns two adjacent 8x16 entries forming one 16x16 marker.
.proc build_oam_shadow
    ldx #0
    lda #$FF
@hide:
    sta oam_shadow,x
    inx
    inx
    inx
    inx
    cpx #64
    bne @hide

    lda packet_count
    sta records_left
    ldy #0
@record:
    lda records_left
    bne :+
    jmp @done
:
    sty rec_offset

    lda scene_payload,y
    sta record_flags
    and #$07
    sta slot_number

    ; Keep the selected marker in the first OAM pair. Rotate the other seven
    ; complete two-sprite markers around it so scanline overflow flickers like
    ; an NES-era object group instead of permanently damaging one target.
    cmp selected_slot
    beq @selected_priority
    sec
    sbc oam_rotation
    and #7
    sta temp                       ; cyclic rank of this slot
    lda selected_slot
    sec
    sbc oam_rotation
    and #7
    sta panel_offset               ; cyclic rank removed for selected slot
    lda temp
    cmp panel_offset
    bcs @priority_ready
    clc
    adc #1                         ; leave OAM pair zero for selected target
@priority_ready:
    asl a
    asl a
    asl a                          ; rotated OAM position * 8
    tax
    jmp @priority_set
@selected_priority:
    ldx #0
@priority_set:

    ; Resolve the independently banked left/right pattern variants.
    lda record_flags
    and #TRACK_INVALID
    beq @have_track
    lda #META_NO_TRACK_LEFT
    sta meta_left
    lda #META_NO_TRACK_RIGHT
    sta meta_right
    jmp @variants_ready
@have_track:
    lda scene_payload + 3,y
    clc
    adc #16                       ; nearest 45-degree sector
    lsr a
    lsr a
    lsr a
    lsr a
    lsr a
    tay
    lda meta_left_variant,y
    sta meta_left
    lda meta_right_variant,y
    sta meta_right
@variants_ready:
    ldy rec_offset

    ; Shared Y for both 8x16 halves.
    lda scene_payload + 2,y
    clc
    adc #META_LDV_OFFSET_Y
    sta oam_shadow + 0,x
    sta oam_shadow + 4,x

    ; Left tile: (slot * 6 + variant) << 1 | 1.
    lda slot_number
    asl a
    sta temp                       ; slot * 2
    asl a
    clc
    adc temp
    clc
    adc meta_left
    asl a
    ora #1                         ; odd tile selects pattern table $1000
    sta oam_shadow + 1,x

    ; Right tile: (48 + slot * 4 + variant) << 1 | 1.
    lda slot_number
    asl a
    asl a
    clc
    adc meta_right
    clc
    adc #META_RIGHT_PAIR_BASE
    asl a
    ora #1
    sta oam_shadow + 5,x

    ; Both halves share attributes. Palette 1 belongs only to the selected
    ; target; packet alert flags do not alter the LDV table-row colours.
    lda #0
    sta oam_shadow + 2,x
    sta oam_shadow + 6,x
    lda slot_number
    cmp selected_slot
    bne @not_selected
    lda #1
    sta oam_shadow + 2,x
    sta oam_shadow + 6,x
@not_selected:

    ; Two halves are exactly eight pixels apart.
    lda scene_payload + 1,y
    clc
    adc #META_LDV_OFFSET_X_LEFT
    sta oam_shadow + 3,x
    lda scene_payload + 1,y
    clc
    adc #META_LDV_OFFSET_X_RIGHT
    sta oam_shadow + 7,x

    tya
    clc
    adc #RECORD_SIZE
    tay
    dec records_left
    beq @done
    jmp @record
@done:
    rts
.endproc

; Clear all dynamic LDV character buffers.
.proc initialize_display_buffers
    ldx #0
    lda #CHAR_SPACE
@identity:
    sta identity_tiles,x
    inx
    cpx #192
    bne @identity
    ldx #0
@selected:
    sta selected_fields,x
    inx
    cpx #37
    bne @selected
    ldx #0
@status:
    sta status_fields,x
    inx
    cpx #STATUS_SIZE
    bne @status

    ldx #0
@airport:
    lda icao_code,x
    jsr identity_char_tile
    sta status_fields + STATUS_APT,x
    inx
    cpx #4
    bne @airport
    jsr set_link_waiting
    lda #CHAR_SPACE
    sta status_fields + STATUS_COUNT
    lda #CHAR_0
    sta status_fields + STATUS_COUNT + 1
    rts
.endproc

; Poll once after an accepted scene. Down/Right selects the next occupied slot;
; Up/Left selects the previous. The cycle-timed receiver is never touched.
.proc update_selection
    jsr latch_controller
    lda controller_pending
    sta controller_pressed
    lda #0
    sta controller_pending
    lda controller_pressed
    and #BUTTON_SELECT
    beq :+
    lda #1
    sta navigation_requested
    rts
:
    jmp move_selection
.endproc

; The slot walk on its own, so a chunk gap can move the selection without
; going near the Select handling above.
.proc move_selection
    lda selected_slot
    sta previous_selected_slot
    lda active_slots
    beq @none
    ldx selected_slot
    lda slot_masks,x
    and active_slots
    bne @poll
    ldx #$FF
@first:
    inx
    lda slot_masks,x
    and active_slots
    beq @first
    stx selected_slot
@poll:
    lda controller_pressed
    and #(BUTTON_DOWN | BUTTON_RIGHT)
    bne @next
    lda controller_pressed
    and #(BUTTON_UP | BUTTON_LEFT)
    bne @previous
    rts
@next:
    ldx selected_slot
    ldy #8
@next_slot:
    inx
    txa
    and #7
    tax
    lda slot_masks,x
    and active_slots
    bne @choose
    dey
    bne @next_slot
    rts
@previous:
    ldx selected_slot
    ldy #8
@previous_slot:
    dex
    txa
    and #7
    tax
    lda slot_masks,x
    and active_slots
    bne @choose
    dey
    bne @previous_slot
    rts
@choose:
    stx selected_slot
    rts
@none:
    lda #0
    sta selected_slot
    rts
.endproc

; A legal zero-record identity packet is used as a short controller/display
; heartbeat. The last scene payload is still resident because the heartbeat
; has no payload. Every heartbeat advances OAM priority so overloaded 16x16
; markers flicker rather than leaving the same halves persistently absent.
.proc service_control_heartbeat
    lda active_slots
    beq @done
    jsr update_selection
    lda displayed_count
    sta packet_count
    jsr build_oam_shadow
    lda selected_slot
    cmp previous_selected_slot
    beq @oam_only
    jsr build_selected_fields
    jsr commit_selection
    jmp @advance
@oam_only:
    jsr commit_oam
@advance:
    inc oam_rotation
    lda oam_rotation
    and #7
    sta oam_rotation
@done:
    rts
.endproc

; Run target flicker and controller polling from the NES vblank clock, exactly
; once per video field. The host guarantees serial silence for this fixed
; window, then resumes ordinary v0-timed packets after the routine returns.
.proc animate_display_window
    lda #<DISPLAY_WINDOW_FRAMES
    sta display_frames_lo
    lda #>DISPLAY_WINDOW_FRAMES
    sta display_frames_hi
@frame:
    jsr update_selection
    lda navigation_requested
    bne @done
    jsr age_link
    lda displayed_count
    sta packet_count
    jsr build_oam_shadow
    lda selected_slot
    cmp previous_selected_slot
    beq @oam_only
    jsr build_selected_fields
    jsr commit_selection
    jmp @advance
@oam_only:
    jsr commit_oam
@advance:
    inc oam_rotation
    lda oam_rotation
    and #7
    sta oam_rotation

    lda display_frames_lo
    bne :+
    dec display_frames_hi
:
    dec display_frames_lo
    lda display_frames_lo
    ora display_frames_hi
    bne @frame

    ; The window is over. From here the ROM listens for the next packet and
    ; stops servicing the controller, so say so before going deaf rather than
    ; after. Only IDLE is overwritten: WAITING and ERROR describe a link that
    ; is not delivering, and claiming RECEIVING over either of them would be a
    ; lie the player has no way to check.
    lda status_fields + STATUS_LINK
    cmp #CHAR_A + ('I' - 'A')
    bne @done
    jsr set_link_receiving
    jsr commit_link_state
@done:
    rts
.endproc

.proc build_selected_identity
    lda active_slots
    beq @done
    ldx selected_slot
    lda slot_masks,x
    and active_slots
    beq @done
    lda selected_slot
    asl a
    asl a
    asl a                          ; slot * 8
    sta temp
    asl a                          ; slot * 16
    clc
    adc temp                       ; slot * 24
    clc
    adc #8                         ; aircraft type follows callsign[8]
    tay
    ldx #0
@copy:
    lda identity_tiles,y
    sta selected_fields + SEL_TYPE,x
    iny
    inx
    cpx #16                        ; TYPE, REG, SQWK, CAT are contiguous
    bne @copy
@done:
    rts
.endproc

; Rebuild all 37 selected-aircraft characters from protocol v2 identity and
; motion records.
.proc build_selected_fields
    ldx #0
    lda #CHAR_SPACE
@clear:
    sta selected_fields,x
    inx
    cpx #37
    bne @clear
    lda active_slots
    bne :+
    jmp @done
:
    lda #CHAR_SPACE
    sta selected_fields + SEL_TGT
    lda selected_slot
    clc
    adc #CHAR_0 + 1
    sta selected_fields + SEL_TGT + 1
    jsr build_selected_identity

    lda packet_count
    sta records_left
    ldy #0
@record:
    lda records_left
    bne :+
    jmp @done
:
    lda scene_payload,y
    and #7
    cmp selected_slot
    beq @found
    tya
    clc
    adc #RECORD_SIZE
    tay
    dec records_left
    bne @record
    rts
@found:
    sty rec_offset
    lda scene_payload,y
    sta record_flags
    and #ALT_INVALID
    bne @speed
    lda scene_payload + 4,y
    sta value_lo
    lda scene_payload + 5,y
    sta value_hi
    jsr convert_u16_3digits
    ldx #0
    lda digit_hundreds
    jsr store_alt_digit
    lda digit_tens
    jsr store_alt_digit
    lda digit_ones
    jsr store_alt_digit
    lda #CHAR_0
    sta selected_fields + SEL_ALT + 3
    sta selected_fields + SEL_ALT + 4
@speed:
    ldy rec_offset
    lda record_flags
    and #SPEED_INVALID
    bne @track
    lda scene_payload + 6,y
    sta value_lo
    lda #0
    sta value_hi
    jsr convert_u16_3digits
    ldx #0
    lda digit_hundreds
    jsr store_speed_digit
    lda digit_tens
    jsr store_speed_digit
    lda digit_ones
    jsr store_speed_digit
@track:
    lda record_flags
    and #TRACK_INVALID
    bne @vertical
    ldy rec_offset
    lda scene_payload + 3,y
    sta track_value
    lda #0
    sta value_lo
    sta value_hi
    ldx #45
@multiply_45:
    clc
    lda value_lo
    adc track_value
    sta value_lo
    lda value_hi
    adc #0
    sta value_hi
    dex
    bne @multiply_45
    clc                             ; round (track * 45) / 32
    lda value_lo
    adc #16
    sta value_lo
    lda value_hi
    adc #0
    sta value_hi
    ldx #5
@divide_32:
    lsr value_hi
    ror value_lo
    dex
    bne @divide_32
    jsr convert_u16_3digits
    ldx #0
    lda digit_hundreds
    jsr store_track_digit
    lda digit_tens
    jsr store_track_digit
    lda digit_ones
    jsr store_track_digit
@vertical:
    ldy rec_offset
    lda scene_payload + 7,y
    cmp #$80                        ; signed-rate unavailable sentinel
    beq @distance
    bcc @vertical_positive
    ldx #CHAR_HYPHEN
    eor #$FF
    clc
    adc #1
    jmp @vertical_magnitude
@vertical_positive:
    ldx #CHAR_PLUS
@vertical_magnitude:
    stx selected_fields + SEL_VS
    sta value_lo
    lda #0
    sta value_hi
    jsr convert_u16_3digits
    lda digit_tens
    clc
    adc #CHAR_0
    sta selected_fields + SEL_VS + 1
    lda digit_ones
    clc
    adc #CHAR_0
    sta selected_fields + SEL_VS + 2
    lda #CHAR_0
    sta selected_fields + SEL_VS + 3
    sta selected_fields + SEL_VS + 4
@distance:
    ldy rec_offset
    lda scene_payload + 8,y
    cmp #$FF                        ; distance unavailable sentinel
    beq @done
    sta value_lo
    lda #0
    sta value_hi
    jsr convert_u16_3digits
    lda digit_tens
    clc
    adc #CHAR_0
    sta selected_fields + SEL_DIST
    lda #CHAR_DOT
    sta selected_fields + SEL_DIST + 1
    lda digit_ones
    clc
    adc #CHAR_0
    sta selected_fields + SEL_DIST + 2
@done:
    rts
.endproc

.proc store_alt_digit
    clc
    adc #CHAR_0
    sta selected_fields + SEL_ALT,x
    inx
    rts
.endproc

.proc store_speed_digit
    clc
    adc #CHAR_0
    sta selected_fields + SEL_SPD,x
    inx
    rts
.endproc

.proc store_track_digit
    clc
    adc #CHAR_0
    sta selected_fields + SEL_TRK,x
    inx
    rts
.endproc

.proc build_status_fields
    lda #CHAR_SPACE
    sta status_fields + STATUS_COUNT
    lda packet_count
    clc
    adc #CHAR_0
    sta status_fields + STATUS_COUNT + 1
    ; A scene was just accepted, so the packet is over and the display window
    ; is about to start. That is the idle half of the cycle, not the receiving
    ; half. RECEIVING is set later, when the window expires.
    jsr set_link_idle
    rts
.endproc

; Entering WAITING used to blank the targets, the table rows, the selected
; aircraft and the count. It no longer does. The last complete scene stays on
; screen and the LINK field is what says the data is old, which is more useful
; than an empty scope: a scope that erases itself the moment the host pauses
; looks broken, and the aircraft that were there a moment ago are still the
; best information available.
;
; The sequence state does have to go. The server restarts its sequence
; numbering on a fresh stream, so a retained have_seq would make the first
; scene back look like a sequence error.
.proc forget_scene_sequence
    lda #0
    sta have_seq
    rts
.endproc

; Remove every visible aircraft while preserving cached identity text for a
; clean recovery when the next current scene arrives. Nothing calls this now
; that WAITING retains its targets. Kept because it is the only correct
; response if a reason to blank the scope comes back.
.proc clear_target_state
    lda #0
    sta active_slots
    sta displayed_count
    sta packet_count
    sta selected_slot
    sta previous_selected_slot
    sta oam_rotation
    sta have_seq
    jsr build_oam_shadow
    jsr build_selected_fields
    lda #CHAR_SPACE
    sta status_fields + STATUS_COUNT
    lda #CHAR_0
    sta status_fields + STATUS_COUNT + 1
    rts
.endproc

; A CRC-valid packet proves that the transport is currently active. Scene
; freshness is tracked separately so a heartbeat cannot make stale ADS-B data
; appear live.
.proc note_valid_packet
    lda #0
    sta link_age_lo
    sta link_age_hi
    sta link_timed_out
    rts
.endproc

; Advance the no-valid-packet age by one video field. Carry is set exactly once
; when the ten-second threshold is crossed and the state becomes WAITING.
.proc age_link
    lda link_timed_out
    bne @unchanged
    inc link_age_lo
    bne :+
    inc link_age_hi
:
    lda link_age_hi
    cmp #>LINK_STALE_FRAMES
    bcc @unchanged
    bne @timeout
    lda link_age_lo
    cmp #<LINK_STALE_FRAMES
    bcc @unchanged
@timeout:
    lda #1
    sta link_timed_out
    sta link_data_stale
    jsr set_link_waiting
    jsr forget_scene_sequence
    sec
    rts
@unchanged:
    clc
    rts
.endproc

; Repaint only the LINK field, waiting for a clean vblank boundary first.
;
; Safe only where the host is known to be quiet. The one caller is the end of
; the display window, which is 360 fields (about 6.00 seconds) out of a 9.500
; second interval. A packet already in flight cannot be interrupted for this,
; which is why the state changes at the window boundary rather than at the
; first start bit.
.proc commit_link_state
    jsr begin_vram_update
    jsr write_link_during_vblank
    rts
.endproc

; Called immediately after observing vblank in the idle marker wait.
.proc write_link_during_vblank
    lda #<(status_fields + STATUS_LINK)
    sta field_src
    lda #>(status_fields + STATUS_LINK)
    sta field_src + 1
    lda #FONT_DIM_BASE
    sta field_font
    ldy #LINK_STATE_WIDTH
    lda #>FLD_LINK
    ldx #<FLD_LINK
    jsr write_field
    jsr restore_scroll
    rts
.endproc

.proc set_link_receiving
    lda #<link_receiving_chars
    ldx #>link_receiving_chars
    jmp copy_link_state
.endproc

.proc set_link_waiting
    lda #<link_waiting_chars
    ldx #>link_waiting_chars
    jmp copy_link_state
.endproc

; The link is healthy and nothing is arriving. This is also the only state in
; which the controller does anything, so it doubles as the cue that the scope
; is yours.
.proc set_link_idle
    lda #<link_idle_chars
    ldx #>link_idle_chars
    jmp copy_link_state
.endproc

.proc set_link_error
    lda #<link_error_chars
    ldx #>link_error_chars
    jmp copy_link_state
.endproc

; A:X points to a fixed-width LINK state in ROM.
.proc copy_link_state
    sta field_src
    stx field_src + 1
    ldy #0
@copy:
    lda (field_src),y
    sta status_fields + STATUS_LINK,y
    iny
    cpy #LINK_STATE_WIDTH
    bne @copy
    rts
.endproc

; Convert value_hi:value_lo to three decimal digits, clipping at 999.
.proc convert_u16_3digits
    lda value_hi
    cmp #3
    bcc @convert
    bne @clip
    lda value_lo
    cmp #$E8                       ; $03E8 = 1000
    bcs @clip
@convert:
    lda #0
    sta digit_hundreds
    sta digit_tens
@hundreds:
    lda value_hi
    bne @subtract_100
    lda value_lo
    cmp #100
    bcc @tens
@subtract_100:
    lda value_lo
    sec
    sbc #100
    sta value_lo
    lda value_hi
    sbc #0
    sta value_hi
    inc digit_hundreds
    jmp @hundreds
@tens:
    lda value_lo
    cmp #10
    bcc @ones
    sec
    sbc #10
    sta value_lo
    inc digit_tens
    jmp @tens
@ones:
    lda value_lo
    sta digit_ones
    rts
@clip:
    lda #9
    sta digit_hundreds
    sta digit_tens
    sta digit_ones
    rts
.endproc

; Read a standard controller from port 1. The final bit layout is convenient
; for edge handling: A,B,Select,Start,Up,Down,Left,Right become bits 7..0.
.proc read_controller
    lda #1
    sta JOY1
    lda #0
    sta JOY1
    sta controller_current
    ldx #8
@button:
    lda JOY1
    and #1
    lsr a
    rol controller_current
    dex
    bne @button
    rts
.endproc

.proc latch_controller
    jsr read_controller
    lda controller_previous
    eor #$FF
    and controller_current
    ora controller_pending
    sta controller_pending
    lda controller_current
    sta controller_previous
    rts
.endproc

; Keep the four ICAO cells as an amber field, draw their editable A-Z values
; as black startup-only sprites, and underline the active position.
.proc render_editor
    jsr begin_vram_update
    bit PPUSTATUS
    lda #>STARTUP_CODE_ADDR
    sta PPUADDR
    lda #<STARTUP_CODE_ADDR
    sta PPUADDR
    ldx #0
    lda #STARTUP_INPUT_FILL
@fill:
    sta PPUDATA
    inx
    cpx #4
    bne @fill

    ldx #0
    ldy #0
@letter:
    lda #STARTUP_SPRITE_Y
    sta oam_shadow + 0,y
    lda icao_code,x
    sec
    sbc #'A'
    asl a
    clc
    adc #STARTUP_LETTER_TILE_BASE
    sta oam_shadow + 1,y
    lda #STARTUP_SPRITE_PALETTE
    sta oam_shadow + 2,y
    txa
    asl a
    asl a
    asl a
    clc
    adc #STARTUP_SPRITE_X
    sta oam_shadow + 3,y
    iny
    iny
    iny
    iny
    inx
    cpx #4
    bne @letter

    ldx #0
    lda #CHAR_SPACE
@clear_cursor:
    sta startup_cursor,x
    inx
    cpx #4
    bne @clear_cursor
    ldx editor_index
    lda #CHAR_HYPHEN
    sta startup_cursor,x
    lda #<startup_cursor
    sta field_src
    lda #>startup_cursor
    sta field_src + 1
    lda #FONT_DIM_BASE
    sta field_font
    ldy #4
    lda #>STARTUP_CURSOR_ADDR
    ldx #<STARTUP_CURSOR_ADDR
    jsr write_field

    lda #<startup_blank_16
    sta field_src
    lda #>startup_blank_16
    sta field_src + 1
    lda #FONT_DIM_BASE
    sta field_font
    ldy #16
    lda #>STARTUP_MESSAGE_ADDR
    ldx #<STARTUP_MESSAGE_ADDR
    jsr write_field
    lda #0
    sta OAMADDR
    lda #>oam_shadow
    sta OAMDMA
    jsr restore_scroll
    rts
.endproc

; A=0 shows REQUESTING; A!=0 shows INVALID AIRPORT.
.proc show_startup_message
    sta temp
    jsr begin_vram_update
    lda temp
    bne @invalid
    lda #<startup_requesting_chars
    ldx #>startup_requesting_chars
    bne @source_ready
@invalid:
    lda #<startup_invalid_chars
    ldx #>startup_invalid_chars
@source_ready:
    sta field_src
    stx field_src + 1
    lda #FONT_DIM_BASE
    sta field_font
    ldy #16
    lda #>STARTUP_MESSAGE_ADDR
    ldx #<STARTUP_MESSAGE_ADDR
    jsr write_field
    jsr restore_scroll
    rts
.endproc

; ---------------------------------------------------------------------------
; Reverse channel, NES to host
; ---------------------------------------------------------------------------
;
; Six bytes on the wire: marker, four payload bytes, XOR checksum seeded
; with $A5. Modulation is 9,600 8N1 UART on OUT0; see ../SIGNALING.md.


; 9600 8N1 transmit on OUT0. Every fact the routine depends on was measured
; on a real NTSC console with a diagnostic ROM before it landed here: 18390
; bytes with zero corruption, a clean baud window of 9200 to
; 10200, and 500 round trips with eight controller strobes each landing
; between the receive and the reply without contaminating either.
;
; NTSC runs at 1.789773 MHz, so a 9600 bit is 186.43 cycles. This uses a flat
; 186, which is 0.23 percent fast. By the stop bit that has accumulated to
; about 2 percent of a bit, well inside what a 16x oversampling receiver
; tolerates.
;
; Every bit costs the same because the data bit reaches OUT0 without a branch:
; LSR drops bit 0 into carry and ADC #0 against A=0 turns the carry back into
; the 0 or 1 that $4016 wants. A branchless path is what makes the loop
; countable in the first place.
;
; Timing is measured write-to-write on STA JOY1, since the write lands on the
; last cycle of the instruction.
;
;   start -> data0 : 171 delay + ldx 2 + lsr 5 + lda 2 + adc 2 + sta 4 = 186
;   data  -> data  : 168 delay + dex 2 + bne 3 + lsr 5 + lda 2 + adc 2 + sta 4
;                                                                     = 186
;   data7 -> stop  : 168 delay + dex 2 + bne 2 + pad 8 + lda 2 + sta 4 = 186
;
; A taken branch costs an extra cycle when it crosses a page, so the delay
; loops are only correct for the addresses the linker happened to give them.
; Do not move this routine or edit around it without re-running
; tools/verify_tx_timing.py, which charges that penalty and checks all 256
; byte values. The failure is silent: the ROM still sends, the host still
; sees bytes, and some fraction of them are wrong.
;
; The stop bit is then held a full bit time before returning, so back-to-back
; calls always leave at least one stop bit of mark between bytes.
;
; The caller must have OUT0 at mark already. Destroys A, X, Y.
;
; The alignment is load-bearing, not tidiness. Both delay loops are three bytes
; and run 33 or 34 times, so if a loop straddles a page boundary every one of
; those iterations pays the extra cycle a taken branch costs across a page and
; the bit period goes from 186 to 219, which is 8170 baud. Nothing on the
; console would report that, it would just corrupt bytes. The routine is 47
; bytes, so a 64-byte boundary keeps it inside one page wherever the linker
; puts it. Adding CHUNK_BYTES support moved this code and broke exactly this,
; caught by tools/verify_tx_timing.py.
.align 64
.proc uart_tx_byte
    sta tx_byte

    lda #0
    sta JOY1                      ; start bit, T0

    ldy #34                       ; 5*34+1 = 171
@start_delay:
    dey
    bne @start_delay

    ldx #8
@bit:
    lsr tx_byte                   ; bit 0 -> carry
    lda #0
    adc #0                        ; A = carry, no branch
    sta JOY1                      ; data bit
    ldy #33                       ; 5*33+1 = 166
@bit_delay:
    dey
    bne @bit_delay
    nop                           ; 166 + 2 = 168
    dex
    bne @bit

    nop                           ; 8 cycles of padding so the stop bit
    nop                           ; lands exactly 186 after data bit 7
    nop
    nop
    lda #1
    sta JOY1                      ; stop bit

    ldy #37                       ; 5*37+1 = 186, one full stop bit
@stop_delay:
    dey
    bne @stop_delay
    rts
.endproc

; X = guard in 100 us units. Raise OUT0 to mark and hold it before the first
; start bit, so a host UART coming out of break has time to re-arm.
;
; The guard is 800 us as deliberate margin, not a tuned figure. A guard
; sweep on real hardware found no floor to tune against: every value from
; the roughly 22 us the ROM cannot help emitting up through 2000 us produced
; complete frames.
.proc begin_mark_x
    lda #1
    sta JOY1
    jsr delay_x_100us
    rts
.endproc

; Drop back to the resting break level. OUT0 low is where read_controller and
; sample_line already leave the pin, so resting there costs nothing and makes
; ordinary controller strobes invisible to the host. It costs at most one 0x00
; at the host on the mark-to-break edge, which the host discards because it
; scans for a marker byte.
.proc end_mark
    lda #0
    sta JOY1
    rts
.endproc

; About 103 us, not 100. Kept at its measured value so the 800 us nominal
; mark guard lands at the same 827 us that hardware measured. Precision is
; not the point of a guard.
.proc delay_100us
    ldy #33
@loop:
    dey
    bne @loop
    nop
    rts
.endproc

.proc delay_x_100us
    cpx #0
    beq @done
@loop:
    jsr delay_100us
    dex
    bne @loop
@done:
    rts
.endproc

; Fill in the checksum over a frame whose marker and payload are already in
; uart_frame, then put all six bytes on the wire.
;
; Checksum: XOR of the marker and payload, seeded with $A5.
.proc send_uart_frame
    lda #OUT0_CHECK_SEED
    ldx #0
@checksum:
    eor uart_frame,x
    inx
    cpx #UART_FRAME_BYTES - 1
    bne @checksum
    sta uart_frame + UART_FRAME_BYTES - 1

    ldx #UART_GUARD_UNITS
    jsr begin_mark_x
    lda #0
    sta tx_index
@send:
    ldx tx_index
    lda uart_frame,x
    jsr uart_tx_byte              ; destroys A, X and Y, hence tx_index
    inc tx_index
    lda tx_index
    cmp #UART_FRAME_BYTES
    bne @send
    jsr end_mark
    rts
.endproc

; Marker $4E, four ASCII ICAO letters, XOR checksum seeded with $A5.
; Six bytes on the wire in about 7.2 ms.
.proc send_location_request
    ldx #0
@copy:
    lda icao_code,x
    sta uart_frame + 1,x
    inx
    cpx #4
    bne @copy
    lda #OUT0_REQUEST_MARKER
    sta uart_frame
    jmp send_uart_frame
.endproc

; Request exclusive controller ownership before exposing the ICAO editor.
; Marker $50 and a zero payload, so the frame is the same length and obeys the
; same checksum as a location request.
.proc send_pause_request
    lda #0
    ldx #0
@pad:
    sta uart_frame + 1,x
    inx
    cpx #4
    bne @pad
    lda #PAUSE_REQUEST_MARKER
    sta uart_frame
    jmp send_uart_frame
.endproc


.proc initialize_startup_video
    lda #0
    sta PPUMASK
    lda #CHR_BANK_RADAR
    jsr select_chr_bank
    jsr load_ldv_palette

    bit PPUSTATUS
    lda #$20
    sta PPUADDR
    lda #$00
    sta PPUADDR
    ldx #0
    lda #CHAR_SPACE
@clear_0:
    sta PPUDATA
    inx
    bne @clear_0
    ldx #0
@clear_1:
    sta PPUDATA
    inx
    bne @clear_1
    ldx #0
@clear_2:
    sta PPUDATA
    inx
    bne @clear_2
    ldx #0
@clear_3:
    sta PPUDATA
    inx
    bne @clear_3
    jsr write_startup_static

    ldx #0
    lda #$FF
@clear_oam:
    sta oam_shadow,x
    inx
    bne @clear_oam
    lda #0
    sta OAMADDR
    lda #>oam_shadow
    sta OAMDMA
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    lda #PPUCTRL_SPR_8X16
    sta PPUCTRL
    lda #SHOW_STARTUP
    sta PPUMASK
    rts
.endproc

.proc initialize_video
    lda #0
    sta PPUMASK
    sta controller_pending
    sta controller_previous
    sta displayed_count
    sta link_age_lo
    sta link_age_hi
    sta link_timed_out
    sta navigation_requested
    sta pause_waiting
    lda #1
    sta link_data_stale
    jsr load_ldv_palette

    bit PPUSTATUS
    lda #$20
    sta PPUADDR
    lda #$00
    sta PPUADDR
    ldx #0
@nametable_0:
    lda ldv_bg_nam,x
    sta PPUDATA
    inx
    bne @nametable_0
    ldx #0
@nametable_1:
    lda ldv_bg_nam + 256,x
    sta PPUDATA
    inx
    bne @nametable_1
    ldx #0
@nametable_2:
    lda ldv_bg_nam + 512,x
    sta PPUDATA
    inx
    bne @nametable_2
    ldx #0
@nametable_3:
    lda ldv_bg_nam + 768,x
    sta PPUDATA
    inx
    cpx #192
    bne @nametable_3

    bit PPUSTATUS
    lda #$23
    sta PPUADDR
    lda #$C0
    sta PPUADDR
    ldx #0
@attributes:
    lda ldv_bg_att,x
    sta PPUDATA
    inx
    cpx #64
    bne @attributes

    ; Rendering is still off, so initialize the short dynamic status fields
    ; without consuming any of the host's existing inter-packet guard time.
    jsr write_status_frame

    ldx #0
    lda #$FF
@clear_oam:
    sta oam_shadow,x
    inx
    bne @clear_oam
    lda #0
    sta OAMADDR
    lda #>oam_shadow
    sta OAMDMA

    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    lda #PPUCTRL_SPR_8X16
    sta PPUCTRL
    lda #SHOW_SCOPE
    sta PPUMASK
    rts
.endproc

.proc load_ldv_palette
    bit PPUSTATUS
    lda #$3F
    sta PPUADDR
    lda #$00
    sta PPUADDR
    ldx #0
@palette:
    lda ldv_palette,x
    sta PPUDATA
    inx
    cpx #32
    bne @palette
    rts
.endproc

.proc write_startup_static
    lda #FONT_DIM_BASE
    sta field_font
    lda #<startup_title
    sta field_src
    lda #>startup_title
    sta field_src + 1
    ldy #9
    lda #>$208B
    ldx #<$208B
    jsr write_field
    lda #<startup_select
    sta field_src
    lda #>startup_select
    sta field_src + 1
    ldy #14
    lda #>$20E8
    ldx #<$20E8
    jsr write_field
    lda #<startup_icao
    sta field_src
    lda #>startup_icao
    sta field_src + 1
    ldy #4
    lda #>$2149
    ldx #<$2149
    jsr write_field
    lda #<startup_up_down
    sta field_src
    lda #>startup_up_down
    sta field_src + 1
    ldy #14
    lda #>$2229
    ldx #<$2229
    jsr write_field
    lda #<startup_left_right
    sta field_src
    lda #>startup_left_right
    sta field_src + 1
    ldy #15
    lda #>$2248
    ldx #<$2248
    jsr write_field
    lda #<startup_confirm
    sta field_src
    lda #>startup_confirm
    sta field_src + 1
    ldy #13
    lda #>$2269
    ldx #<$2269
    jsr write_field
    lda #0
    sta field_font
    lda #<startup_traffic_source
    sta field_src
    lda #>startup_traffic_source
    sta field_src + 1
    ldy #23
    lda #>$22A4
    ldx #<$22A4
    jsr write_field
    lda #<startup_levimaaia
    sta field_src
    lda #>startup_levimaaia
    sta field_src + 1
    ldy #13
    lda #>$22E9
    ldx #<$22E9
    jsr write_field
    lda #<startup_youtube
    sta field_src
    lda #>startup_youtube
    sta field_src + 1
    ldy #22
    lda #>$2305
    ldx #<$2305
    jsr write_field
    bit PPUSTATUS
    lda #>$23DB
    sta PPUADDR
    lda #<$23DB
    sta PPUADDR
    lda #%00001000                 ; palette 2, right/top quadrant at cols 14-15
    sta PPUDATA
    lda #%00000010                 ; palette 2, left/top quadrant at cols 16-17
    sta PPUDATA
    rts
.endproc

; The LDV contract's four rendered vblanks. Frame A also performs OAM DMA;
; rendering remains enabled throughout every dynamic update.
.proc commit_display
    jsr begin_vram_update
    lda #0
    sta OAMADDR
    lda #>oam_shadow
    sta OAMDMA
    jsr write_selected_frame
    jsr restore_scroll

    jsr begin_vram_update
    ldx #0
    jsr write_table_half
    jsr restore_scroll

    jsr begin_vram_update
    ldx #4
    jsr write_table_half
    jsr restore_scroll

    jsr begin_vram_update
    jsr write_status_frame
    jsr restore_scroll
    rts
.endproc

; A selection-only change fits in one rendered vblank: OAM DMA, the 37-tile
; selected panel, and two one-tile table-slot updates.
.proc commit_selection
    jsr begin_vram_update
    jmp commit_selection_in_vblank
.endproc

; The same payload with the wait removed, for a caller that has just observed
; vblank itself and cannot afford to spend another frame blind to the wire.
.proc commit_selection_in_vblank
    lda #0
    sta OAMADDR
    lda #>oam_shadow
    sta OAMDMA
    jmp commit_selection_fields
.endproc

; The nametable half on its own, without the OAM DMA. Counted, because this
; runs on a vblank the caller found by polling rather than by NMI and the
; margin is what keeps it off the visible frame:
;
;   write_selected_frame    about 1336 cycles, 35 tiles across nine fields
;   write_selection_slots   about  66
;   restore_scroll          about  36
;                          -----
;                           about 1438, against 2273 cycles of NTSC vblank
;
; Adding the 520-cycle OAM DMA would push that to 1958 and leave under ten
; percent of margin. Skipping it costs nothing here: the marker wait does not
; run build_oam_shadow, so the shadow has not changed since the last commit,
; and the shipped ROM already spent this entire wait without a single DMA.
.proc commit_selection_fields
    jsr write_selected_frame
    jsr write_selection_slots
    jsr restore_scroll
    rts
.endproc

; Heartbeat flicker changes only OAM priority. The host leaves a protected
; quiet interval after the packet, so this one rendered-vblank DMA completes
; before the next serial start bit.
.proc commit_oam
    jsr begin_vram_update
    lda #0
    sta OAMADDR
    lda #>oam_shadow
    sta OAMDMA
    jsr restore_scroll
    rts
.endproc

.proc write_selection_slots
    ldx previous_selected_slot
    bit PPUSTATUS
    lda table_slot_addr_hi,x
    sta PPUADDR
    lda table_slot_addr_lo,x
    sta PPUADDR
    txa
    clc
    adc #CHAR_0 + 1 + FONT_BASE
    sta PPUDATA

    ldx selected_slot
    bit PPUSTATUS
    lda table_slot_addr_hi,x
    sta PPUADDR
    lda table_slot_addr_lo,x
    sta PPUADDR
    txa
    clc
    adc #FONT_INV_BASE
    sta PPUDATA
    rts
.endproc

.proc write_selected_frame
    ; FLD_TGT is the one mixed-font field: a dim space plus inverse slot digit.
    bit PPUSTATUS
    lda #>FLD_TGT
    sta PPUADDR
    lda #<FLD_TGT
    sta PPUADDR
    lda #CHAR_SPACE + FONT_DIM_BASE
    sta PPUDATA
    lda active_slots
    beq @blank_target
    lda selected_slot
    clc
    adc #FONT_INV_BASE
    bne @target_ready
@blank_target:
    lda #CHAR_SPACE + FONT_DIM_BASE
@target_ready:
    sta PPUDATA

    lda #FONT_DIM_BASE
    sta field_font
    lda #<(selected_fields + SEL_TYPE)
    sta field_src
    lda #>(selected_fields + SEL_TYPE)
    sta field_src + 1
    ldy #4
    lda #>FLD_TYPE
    ldx #<FLD_TYPE
    jsr write_field
    lda #<(selected_fields + SEL_REG)
    sta field_src
    lda #>(selected_fields + SEL_REG)
    sta field_src + 1
    ldy #6
    lda #>FLD_REG
    ldx #<FLD_REG
    jsr write_field
    lda #<(selected_fields + SEL_SQWK)
    sta field_src
    lda #>(selected_fields + SEL_SQWK)
    sta field_src + 1
    ldy #4
    lda #>FLD_SQWK
    ldx #<FLD_SQWK
    jsr write_field
    lda #<(selected_fields + SEL_CAT)
    sta field_src
    lda #>(selected_fields + SEL_CAT)
    sta field_src + 1
    ldy #2
    lda #>FLD_CAT
    ldx #<FLD_CAT
    jsr write_field
    lda #<(selected_fields + SEL_ALT)
    sta field_src
    lda #>(selected_fields + SEL_ALT)
    sta field_src + 1
    ldy #5
    lda #>FLD_ALT
    ldx #<FLD_ALT
    jsr write_field
    lda #<(selected_fields + SEL_SPD)
    sta field_src
    lda #>(selected_fields + SEL_SPD)
    sta field_src + 1
    ldy #3
    lda #>FLD_SPD
    ldx #<FLD_SPD
    jsr write_field
    lda #<(selected_fields + SEL_TRK)
    sta field_src
    lda #>(selected_fields + SEL_TRK)
    sta field_src + 1
    ldy #3
    lda #>FLD_TRK
    ldx #<FLD_TRK
    jsr write_field
    lda #<(selected_fields + SEL_VS)
    sta field_src
    lda #>(selected_fields + SEL_VS)
    sta field_src + 1
    ldy #5
    lda #>FLD_VS
    ldx #<FLD_VS
    jsr write_field
    lda #<(selected_fields + SEL_DIST)
    sta field_src
    lda #>(selected_fields + SEL_DIST)
    sta field_src + 1
    ldy #3
    lda #>FLD_DIST
    ldx #<FLD_DIST
    jsr write_field
    rts
.endproc

; Four slots: slot digit, seven callsign characters, four type characters.
.proc write_table_half
    stx table_slot_index
    lda #4
    sta table_rows_left
@slot:
    ldx table_slot_index
    bit PPUSTATUS
    lda table_slot_addr_hi,x
    sta PPUADDR
    lda table_slot_addr_lo,x
    sta PPUADDR
    cpx selected_slot
    bne @normal_slot
    lda active_slots
    and slot_masks,x
    beq @normal_slot
    txa
    clc
    adc #FONT_INV_BASE
    bne @write_slot
@normal_slot:
    txa
    clc
    adc #CHAR_0 + 1 + FONT_BASE
@write_slot:
    sta PPUDATA

    lda table_slot_index
    asl a
    asl a
    asl a                          ; slot * 8
    sta temp
    asl a                          ; slot * 16
    clc
    adc temp                       ; slot * 24
    sta identity_offset
    clc
    adc #<identity_tiles
    sta field_src
    lda #>identity_tiles
    adc #0
    sta field_src + 1
    ldx table_slot_index
    lda slot_masks,x
    and active_slots
    bne @identity_source_ready
    lda #<blank_identity_row
    sta field_src
    lda #>blank_identity_row
    sta field_src + 1
@identity_source_ready:
    lda table_slot_index
    and #1
    beq @bright_row
    lda #FONT_BASE
    bne @font_ready
@bright_row:
    lda #FONT_DIM_BASE
@font_ready:
    sta field_font
    ldx table_slot_index
    ldy #7
    lda table_call_addr_hi,x
    pha
    lda table_call_addr_lo,x
    tax
    pla
    jsr write_field

    clc
    lda field_src
    adc #8
    sta field_src
    lda field_src + 1
    adc #0
    sta field_src + 1
    ldx table_slot_index
    ldy #4
    lda table_type_addr_hi,x
    pha
    lda table_type_addr_lo,x
    tax
    pla
    jsr write_field

    inc table_slot_index
    dec table_rows_left
    beq :+
    jmp @slot
:
    rts
.endproc

.proc write_status_frame
    lda #FONT_DIM_BASE
    sta field_font
    lda #<(status_fields + STATUS_COUNT)
    sta field_src
    lda #>(status_fields + STATUS_COUNT)
    sta field_src + 1
    ldy #2
    lda #>FLD_COUNT
    ldx #<FLD_COUNT
    jsr write_field
    lda #<(status_fields + STATUS_APT)
    sta field_src
    lda #>(status_fields + STATUS_APT)
    sta field_src + 1
    ldy #4
    lda #>FLD_APT
    ldx #<FLD_APT
    jsr write_field
    lda #<(status_fields + STATUS_LINK)
    sta field_src
    lda #>(status_fields + STATUS_LINK)
    sta field_src + 1
    ldy #LINK_STATE_WIDTH
    lda #>FLD_LINK
    ldx #<FLD_LINK
    jsr write_field
    rts
.endproc

; A:X = PPU address high:low, field_src = source character indices,
; Y = fixed width, field_font = font base. Every call writes exactly Y tiles.
.proc write_field
    sta field_addr_hi
    stx field_addr_lo
    sty field_width
    bit PPUSTATUS
    lda field_addr_hi
    sta PPUADDR
    lda field_addr_lo
    sta PPUADDR
    ldy #0
@tile:
    lda (field_src),y
    clc
    adc field_font
    sta PPUDATA
    iny
    cpy field_width
    bne @tile
    rts
.endproc

; Preserve the receiver's error paths and surface the reason through the LDV
; LINK field as ERROR 1 through ERROR 5. The number distinguishes UART
; framing, header, CRC, record validation, and scene sequence failures without
; weakening the receiver or requiring a separate diagnostic ROM.
.proc show_error
    sta error_code
    jsr set_link_error
    lda error_code
    clc
    adc #CHAR_0
    sta status_fields + STATUS_LINK + 6
    jsr begin_vram_update
    jsr write_status_frame
    jsr restore_scroll
    rts
.endproc

; Arm NMI only long enough to acquire an exact vblank boundary. Rendering is
; deliberately left enabled: forced blank skips the pre-render scroll reload
; and was the diagnosed cause of the earlier one-tile vertical displacement.
.proc begin_vram_update
    ; UART reception runs with NMI disabled. Once a complete packet is safely
    ; buffered, arm NMI only long enough to get an exact vblank boundary.
    lda #0
    sta vblank_ready
    bit PPUSTATUS
    lda #PPUCTRL_UPDATE_NMI
    sta PPUCTRL
@wait:
    lda vblank_ready
    beq @wait
    lda #PPUCTRL_SPR_8X16
    sta PPUCTRL
    bit PPUSTATUS
    rts
.endproc

.proc restore_scroll
    ; PPUADDR and PPUSCROLL share the write toggle. Reset it explicitly before
    ; restoring scroll so a marginal/late address write cannot pair with the
    ; first scroll byte and leave the nametable displaced.
    bit PPUSTATUS
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    lda #PPUCTRL_SPR_8X16
    sta PPUCTRL
    rts
.endproc

.proc wait_vblank
@wait_end:
    bit PPUSTATUS
    bmi @wait_end
@wait_start:
    bit PPUSTATUS
    bpl @wait_start
    rts
.endproc

.proc nmi
    pha
    lda #1
    sta vblank_ready
    pla
    rti
.endproc

.proc irq
    rti
.endproc

; CN-ROM's discrete latch can have PRG bus conflicts.  BANKDATA begins at
; $8000 with bytes 0,1,2,3, so A and the ROM byte always agree on the write.
.proc select_chr_bank
    tax
    sta chr_bank_values,x
    rts
.endproc

.proc initialize_splash_video
    lda #0
    sta PPUMASK
    sta PPUCTRL
    lda #CHR_BANK_SPLASH
    jsr select_chr_bank

    bit PPUSTATUS
    lda #$3F
    sta PPUADDR
    lda #$00
    sta PPUADDR
    ldx #0
@palette:
    lda splash_bg_palette,x
    sta PPUDATA
    inx
    cpx #16
    bne @palette

    bit PPUSTATUS
    lda #$20
    sta PPUADDR
    lda #$00
    sta PPUADDR
    ldx #0
@nametable_0:
    lda splash_bg_nam,x
    sta PPUDATA
    inx
    bne @nametable_0
    ldx #0
@nametable_1:
    lda splash_bg_nam + 256,x
    sta PPUDATA
    inx
    bne @nametable_1
    ldx #0
@nametable_2:
    lda splash_bg_nam + 512,x
    sta PPUDATA
    inx
    bne @nametable_2
    ldx #0
@nametable_3:
    lda splash_bg_nam + 768,x
    sta PPUDATA
    inx
    bne @nametable_3

    jsr draw_version_stamp

    ldx #0
    lda #$FF
@clear_oam:
    sta oam_shadow,x
    inx
    bne @clear_oam
    lda #0
    sta OAMADDR
    lda #>oam_shadow
    sta OAMDMA
    lda #0
    sta PPUSCROLL
    sta PPUSCROLL
    sta PPUCTRL
    lda #SHOW_BACKGROUND
    sta PPUMASK
    rts
.endproc

; Writes the product name and build version into the blank strip below the logo,
; so a ROM that turns up in the wild says what it is and which build it is.  The
; splash nametable itself is left alone; the text is painted over it after the
; upload.  Rendering is still off at this point, so this does not have to fit in
; vblank.
.proc draw_version_stamp
    bit PPUSTATUS
    lda #>SPLASH_TITLE_ADDR
    sta PPUADDR
    lda #<SPLASH_TITLE_ADDR
    sta PPUADDR
    ldx #0
@title:
    lda splash_title,x
    sta PPUDATA
    inx
    cpx #SPLASH_TITLE_LENGTH
    bne @title

    bit PPUSTATUS
    lda #>VERSION_STAMP_ADDR
    sta PPUADDR
    lda #<VERSION_STAMP_ADDR
    sta PPUADDR
    ldx #0
@glyph:
    lda version_stamp,x
    sta PPUDATA
    inx
    cpx #VERSION_STAMP_LENGTH
    bne @glyph
    rts
.endproc

.proc wait_splash
    lda #SPLASH_FRAMES
    sta splash_frames
@frame:
    jsr wait_vblank
    jsr read_controller
    lda controller_current
    and #BUTTON_START
    bne @release
    dec splash_frames
    bne @frame
    rts
@release:
    jsr wait_vblank
    jsr read_controller
    lda controller_current
    and #BUTTON_START
    bne @release
    rts
.endproc

.segment "BANKDATA"
chr_bank_values:
    .byte $00, $01, $02, $03

.segment "SPLASHDATA"
splash_bg_palette:
    .incbin "assets/splash/splash_bg.palette.bin"
splash_bg_nam:
    .incbin "assets/splash/splash_bg.nam"

; "NES RADAR"
splash_title:
    .byte VER_N, VER_E, VER_S, VER_SPACE, VER_R, VER_A, VER_D, VER_A, VER_R
SPLASH_TITLE_LENGTH = * - splash_title

; "V0.4.3" -- the release version. Bump this, README.md, server/VERSION,
; APP_VERSION in nes_radar_server.py, and start_nes_radar_server.py's
; docstring together. The splash stamp is the only way to tell what is on
; a cartridge or in a .nes file once it is out of context.
version_stamp:
    .byte VER_V, VER_0 + 0, VER_DOT, VER_0 + 4, VER_DOT, VER_0 + 3
VERSION_STAMP_LENGTH = * - version_stamp

.segment "RODATA"
slot_masks:
    .byte $01, $02, $04, $08, $10, $20, $40, $80

link_receiving_chars:
    .byte CHAR_A + ('R' - 'A'), CHAR_A + ('E' - 'A')
    .byte CHAR_A + ('C' - 'A'), CHAR_A + ('E' - 'A')
    .byte CHAR_A + ('I' - 'A'), CHAR_A + ('V' - 'A')
    .byte CHAR_A + ('I' - 'A'), CHAR_A + ('N' - 'A')
    .byte CHAR_A + ('G' - 'A')
link_waiting_chars:
    .byte CHAR_A + ('W' - 'A'), CHAR_A + ('A' - 'A')
    .byte CHAR_A + ('I' - 'A'), CHAR_A + ('T' - 'A')
    .byte CHAR_A + ('I' - 'A'), CHAR_A + ('N' - 'A')
    .byte CHAR_A + ('G' - 'A'), CHAR_SPACE, CHAR_SPACE
link_idle_chars:
    .byte CHAR_A + ('I' - 'A'), CHAR_A + ('D' - 'A')
    .byte CHAR_A + ('L' - 'A'), CHAR_A + ('E' - 'A')
    .byte CHAR_SPACE, CHAR_SPACE, CHAR_SPACE, CHAR_SPACE, CHAR_SPACE
link_error_chars:
    .byte CHAR_A + ('E' - 'A'), CHAR_A + ('R' - 'A')
    .byte CHAR_A + ('R' - 'A'), CHAR_A + ('O' - 'A')
    .byte CHAR_A + ('R' - 'A'), CHAR_SPACE, CHAR_SPACE, CHAR_SPACE, CHAR_SPACE

blank_identity_row:
    .repeat 12
        .byte CHAR_SPACE
    .endrepeat

startup_title:
    .byte CHAR_A+('N'-'A'),CHAR_A+('E'-'A'),CHAR_A+('S'-'A'),CHAR_SPACE
    .byte CHAR_A+('R'-'A'),CHAR_A+('A'-'A'),CHAR_A+('D'-'A'),CHAR_A+('A'-'A'),CHAR_A+('R'-'A')
startup_select:
    .byte CHAR_A+('S'-'A'),CHAR_A+('E'-'A'),CHAR_A+('L'-'A'),CHAR_A+('E'-'A'),CHAR_A+('C'-'A'),CHAR_A+('T'-'A'),CHAR_SPACE
    .byte CHAR_A+('A'-'A'),CHAR_A+('I'-'A'),CHAR_A+('R'-'A'),CHAR_A+('P'-'A'),CHAR_A+('O'-'A'),CHAR_A+('R'-'A'),CHAR_A+('T'-'A')
startup_icao:
    .byte CHAR_A+('I'-'A'),CHAR_A+('C'-'A'),CHAR_A+('A'-'A'),CHAR_A+('O'-'A')
startup_up_down:
    .byte CHAR_A+('U'-'A'),CHAR_A+('P'-'A'),CHAR_SPACE,CHAR_A+('D'-'A'),CHAR_A+('O'-'A'),CHAR_A+('W'-'A'),CHAR_A+('N'-'A'),CHAR_SPACE
    .byte CHAR_A+('C'-'A'),CHAR_A+('H'-'A'),CHAR_A+('A'-'A'),CHAR_A+('N'-'A'),CHAR_A+('G'-'A'),CHAR_A+('E'-'A')
startup_left_right:
    .byte CHAR_A+('L'-'A'),CHAR_A+('E'-'A'),CHAR_A+('F'-'A'),CHAR_A+('T'-'A'),CHAR_SPACE
    .byte CHAR_A+('R'-'A'),CHAR_A+('I'-'A'),CHAR_A+('G'-'A'),CHAR_A+('H'-'A'),CHAR_A+('T'-'A'),CHAR_SPACE
    .byte CHAR_A+('M'-'A'),CHAR_A+('O'-'A'),CHAR_A+('V'-'A'),CHAR_A+('E'-'A')
startup_confirm:
    .byte CHAR_A+('S'-'A'),CHAR_A+('T'-'A'),CHAR_A+('A'-'A'),CHAR_A+('R'-'A'),CHAR_A+('T'-'A'),CHAR_SPACE
    .byte CHAR_A+('C'-'A'),CHAR_A+('O'-'A'),CHAR_A+('N'-'A'),CHAR_A+('F'-'A'),CHAR_A+('I'-'A'),CHAR_A+('R'-'A'),CHAR_A+('M'-'A')
startup_traffic_source:
    .byte FONT_DIM_BASE+CHAR_A+('T'-'A'),STARTUP_CHAR_R,STARTUP_CHAR_A,STARTUP_CHAR_F,STARTUP_CHAR_F,STARTUP_CHAR_I,STARTUP_CHAR_C
    .byte FONT_DIM_BASE+CHAR_SPACE,FONT_DIM_BASE+CHAR_A+('S'-'A'),STARTUP_CHAR_O,STARTUP_CHAR_U,STARTUP_CHAR_R,STARTUP_CHAR_C,STARTUP_CHAR_E
    .byte FONT_DIM_BASE+CHAR_COLON,FONT_DIM_BASE+CHAR_SPACE,STARTUP_CHAR_A,STARTUP_CHAR_D,STARTUP_CHAR_S,STARTUP_CHAR_B
    .byte FONT_DIM_BASE+CHAR_DOT,STARTUP_CHAR_F,STARTUP_CHAR_I
startup_levimaaia:
    .byte STARTUP_CHAR_L,STARTUP_CHAR_E,STARTUP_CHAR_V,STARTUP_CHAR_I,STARTUP_CHAR_M,STARTUP_CHAR_A,STARTUP_CHAR_A,STARTUP_CHAR_I,STARTUP_CHAR_A
    .byte FONT_DIM_BASE+CHAR_DOT,STARTUP_CHAR_C,STARTUP_CHAR_O,STARTUP_CHAR_M
startup_youtube:
    .byte STARTUP_CHAR_Y,STARTUP_CHAR_O,STARTUP_CHAR_U,STARTUP_CHAR_T,STARTUP_CHAR_U,STARTUP_CHAR_B,STARTUP_CHAR_E
    .byte FONT_DIM_BASE+CHAR_DOT,STARTUP_CHAR_C,STARTUP_CHAR_O,STARTUP_CHAR_M,FONT_DIM_BASE+CHAR_SLASH,STARTUP_CHAR_AT
    .byte STARTUP_CHAR_L,STARTUP_CHAR_E,STARTUP_CHAR_V,STARTUP_CHAR_I,STARTUP_CHAR_M,STARTUP_CHAR_A,STARTUP_CHAR_A,STARTUP_CHAR_I,STARTUP_CHAR_A
startup_requesting_chars:
    .byte CHAR_SPACE,CHAR_SPACE,CHAR_SPACE
    .byte CHAR_A+('R'-'A'),CHAR_A+('E'-'A'),CHAR_A+('Q'-'A'),CHAR_A+('U'-'A'),CHAR_A+('E'-'A')
    .byte CHAR_A+('S'-'A'),CHAR_A+('T'-'A'),CHAR_A+('I'-'A'),CHAR_A+('N'-'A'),CHAR_A+('G'-'A')
    .byte CHAR_SPACE,CHAR_SPACE,CHAR_SPACE
startup_invalid_chars:
    .byte CHAR_A+('I'-'A'),CHAR_A+('N'-'A'),CHAR_A+('V'-'A'),CHAR_A+('A'-'A'),CHAR_A+('L'-'A'),CHAR_A+('I'-'A'),CHAR_A+('D'-'A'),CHAR_SPACE
    .byte CHAR_A+('A'-'A'),CHAR_A+('I'-'A'),CHAR_A+('R'-'A'),CHAR_A+('P'-'A'),CHAR_A+('O'-'A'),CHAR_A+('R'-'A'),CHAR_A+('T'-'A'),CHAR_SPACE
startup_blank_16:
    .res 16, CHAR_SPACE

table_slot_addr_hi:
    .byte >TBL1_SLOT,>TBL2_SLOT,>TBL3_SLOT,>TBL4_SLOT,>TBL5_SLOT,>TBL6_SLOT,>TBL7_SLOT,>TBL8_SLOT
table_slot_addr_lo:
    .byte <TBL1_SLOT,<TBL2_SLOT,<TBL3_SLOT,<TBL4_SLOT,<TBL5_SLOT,<TBL6_SLOT,<TBL7_SLOT,<TBL8_SLOT
table_call_addr_hi:
    .byte >TBL1_CALL,>TBL2_CALL,>TBL3_CALL,>TBL4_CALL,>TBL5_CALL,>TBL6_CALL,>TBL7_CALL,>TBL8_CALL
table_call_addr_lo:
    .byte <TBL1_CALL,<TBL2_CALL,<TBL3_CALL,<TBL4_CALL,<TBL5_CALL,<TBL6_CALL,<TBL7_CALL,<TBL8_CALL
table_type_addr_hi:
    .byte >TBL1_TYPE,>TBL2_TYPE,>TBL3_TYPE,>TBL4_TYPE,>TBL5_TYPE,>TBL6_TYPE,>TBL7_TYPE,>TBL8_TYPE
table_type_addr_lo:
    .byte <TBL1_TYPE,<TBL2_TYPE,<TBL3_TYPE,<TBL4_TYPE,<TBL5_TYPE,<TBL6_TYPE,<TBL7_TYPE,<TBL8_TYPE

.include "assets_metasprite_tables.inc"

ldv_bg_nam:
    .incbin "assets/ldv/ldv_bg.nam"
ldv_bg_att:
    .incbin "assets/ldv/ldv_bg.att"

.segment "VECTORS"
    .addr nmi, reset, irq

.segment "CHR0"
    ; splash_bg.chr leaves tiles $E6-$FF blank; the stamp glyphs go there
    ; instead, lifted from the LDV font so the stamp matches the text the rest of
    ; the ROM draws.  $E6-$EF are digits 0-9, $F0 '.', $F1 'V', $F2-$F7 N E S R A D.
    .incbin "assets/splash/splash_bg.chr", 0, VER_GLYPH_BASE * 16
    .incbin "assets/ldv/ldv_bg.chr", CHAR_0 * 16, 10 * 16
    .incbin "assets/ldv/ldv_bg.chr", CHAR_DOT * 16, 16
    .incbin "assets/ldv/ldv_bg.chr", (CHAR_A + 'V' - 'A') * 16, 16
    .incbin "assets/ldv/ldv_bg.chr", (CHAR_A + 'N' - 'A') * 16, 16
    .incbin "assets/ldv/ldv_bg.chr", (CHAR_A + 'E' - 'A') * 16, 16
    .incbin "assets/ldv/ldv_bg.chr", (CHAR_A + 'S' - 'A') * 16, 16
    .incbin "assets/ldv/ldv_bg.chr", (CHAR_A + 'R' - 'A') * 16, 16
    .incbin "assets/ldv/ldv_bg.chr", (CHAR_A + 'A' - 'A') * 16, 16
    .incbin "assets/ldv/ldv_bg.chr", (CHAR_A + 'D' - 'A') * 16, 16
    .res $1000 - (VER_GLYPH_BASE + VER_GLYPH_COUNT) * 16, $00
    .res $1000, $00

.segment "CHR1"
    .incbin "assets/ldv/ldv_bg.chr"
    .incbin "build/radar_sprites_16.chr"

.segment "CHR2"
    .incbin "assets/ldv/ldv_bg.chr"
    .incbin "build/radar_sprites_16.chr"

.segment "CHR3"
    .incbin "assets/ldv/ldv_bg.chr"
    .incbin "build/radar_sprites_16.chr"
