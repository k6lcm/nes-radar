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
DISPLAY_WINDOW_FRAMES = 448       ; 7.47 seconds at NTSC field rate
LINK_STALE_FRAMES     = 600       ; 10 seconds without a valid packet
SPLASH_FRAMES         = 120       ; about two seconds at NTSC field rate
CHR_BANK_SPLASH       = 0
CHR_BANK_RADAR        = 1

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
pulse_byte:     .res 1
pulse_checksum: .res 1
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
    lda #4                         ; target flags/slot/coordinate validation
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
    jsr clear_target_state
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
    pla
    tay
    pla
    tax
    pla
    plp
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
; at most once per video field. Controller polling is deliberately confined to
; the guaranteed post-scene display window so a framed pause can never begin
; too close to the next host packet deadline.
.proc service_idle_if_vblank
    bit PPUSTATUS
    bpl @done
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
    jsr set_link_receiving
    rts
.endproc

; Remove every visible aircraft while preserving cached identity text for a
; clean recovery when the next current scene arrives.
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
    jsr clear_target_state
    sec
    rts
@unchanged:
    clc
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

; Emit a slow, self-framing six-byte request through controller-port OUT0.
; Packet: $4E, four ASCII ICAO letters, XOR checksum seeded with $A5.
; A 200 ms leader and pulse-width bits reuse the repository's exercised OUT0
; reporting convention: 20 ms HIGH=0, 60 ms HIGH=1, 20 ms LOW delimiter.
.proc send_location_request
    lda #OUT0_CHECK_SEED
    eor #OUT0_REQUEST_MARKER
    ldx #0
@checksum:
    eor icao_code,x
    inx
    cpx #4
    bne @checksum
    sta pulse_checksum

    lda #0
    sta JOY1
    lda #25                        ; 500 ms idle gap
    jsr delay_n_20ms
    lda #1
    sta JOY1
    lda #10                        ; 200 ms leader
    jsr delay_n_20ms
    lda #0
    sta JOY1
    lda #10                        ; 200 ms leader separator
    jsr delay_n_20ms

    lda #OUT0_REQUEST_MARKER
    jsr send_pulse_byte
    ldx #0
@code:
    lda icao_code,x
    jsr send_pulse_byte
    inx
    cpx #4
    bne @code
    lda pulse_checksum
    jsr send_pulse_byte
    lda #0
    sta JOY1
    lda #10
    jsr delay_n_20ms
    rts
.endproc

; Request exclusive controller ownership before exposing the ICAO editor.
; Reuse the proven location-request preamble, then emit a distinct 100 ms pause
; symbol. The complete one-second shape survives USB CTS sampling; repeated
; controller latch strobes cannot synthesize its 500/200/200 ms framing.
.proc send_pause_request
    lda #0
    sta JOY1
    lda #25
    jsr delay_n_20ms
    lda #1
    sta JOY1
    lda #10
    jsr delay_n_20ms
    lda #0
    sta JOY1
    lda #10
    jsr delay_n_20ms
    lda #1
    sta JOY1
    lda #5
    jsr delay_n_20ms
    lda #0
    sta JOY1
    rts
.endproc

; Send A most-significant bit first. X is preserved for the four-byte loop.
.proc send_pulse_byte
    sta pulse_byte
    txa
    pha
    ldx #8
@bit:
    asl pulse_byte
    lda #1
    sta JOY1
    lda #1
    bcc @hold
    lda #3
@hold:
    jsr delay_n_20ms
    lda #0
    sta JOY1
    jsr delay_20ms
    dex
    bne @bit
    pla
    tax
    rts
.endproc

.proc delay_20ms
    txa
    pha
    ldy #28
@outer:
    ldx #0
@inner:
    dex
    bne @inner
    dey
    bne @outer
    pla
    tax
    rts
.endproc

.proc delay_n_20ms
    sta delay_blocks
@block:
    jsr delay_20ms
    dec delay_blocks
    bne @block
    rts
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
    lda #0
    sta OAMADDR
    lda #>oam_shadow
    sta OAMDMA
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

; Preserve the receiver's error paths but surface them through the LDV LINK
; field. The old design's separate numeric error cell no longer exists.
.proc show_error
    sta error_code
    jsr set_link_error
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
    .incbin "assets/splash/splash_bg.chr"
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
