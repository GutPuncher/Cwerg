(module main [] :
(import test)
(import fmt)

(import bitstream)

(global DataFF auto (array_val 1024 u8 [ 0xff ]))

(fun test1 [] void :
    (@ref let! bs auto (rec_val bitstream::Stream32 [(field_val DataFF)]))
    (test::AssertEq# (bitstream::Stream32GetBits [(&! bs) 1]) 1_u32)
    (test::AssertEq# (bitstream::Stream32GetBits [(&! bs) 2]) 3_u32)
    (test::AssertEq# (bitstream::Stream32GetBits [(&! bs) 3]) 7_u32)

    (test::AssertEq# (bitstream::Stream32GetBits [(&! bs) 32]) 0xffffffff_u32)
    (test::AssertEq# (. bs bits_count) 2_u8)
    (test::AssertEq# (. bs bits_cache) 3_u8)
    (test::AssertEq# (. bs offset) 5_uint)
    (test::AssertFalse# (. bs eos))

    (test::AssertEq# (bitstream::Stream32GetBits [(&! bs) 31]) 0x7fffffff_u32)
    (test::AssertEq# (. bs bits_count) 3_u8)
    (test::AssertEq# (. bs bits_cache) 7_u8)
    (test::AssertEq# (. bs offset) 9_uint)
    (test::AssertFalse# (. bs eos))

    (test::AssertEq# (bitstream::Stream32GetBits [(&! bs) 30]) 0x3fffffff_u32)
    (test::AssertEq# (. bs bits_count) 5_u8)
    (test::AssertEq# (. bs bits_cache) 0x1f_u8)
    (test::AssertEq# (. bs offset) 13_uint)
    (test::AssertFalse# (. bs eos))

    (test::AssertEq# (bitstream::Stream32BytesLeft [(& bs)]) 1011_uint)
    (test::AssertEq# (front (bitstream::Stream32GetByteSlice [(&! bs) 1000_uint]))
        (pinc (front DataFF) 13))
    (test::AssertEq# (bitstream::Stream32BytesLeft [(& bs)]) 11_uint)

    (test::AssertFalse# (. bs eos))
)

(global Data123 auto (array_val 1024 u8 [
    0x12 0x34 0x56 0x78 0x12 0x34 0x56 0x78
    0x12 0x34 0x56 0x78 0x12 0x34 0x56 0x78
    0x12 0x34 0x56 0x78 0x12 0x34 0x56 0x78
    0x12 0x34 0x56 0x78 0x12 0x34 0x56 0x78
    0x12 0x34 0x56 0x78 0x12 0x34 0x56 0x78
    0x12 0x34 0x56 0x78 0x12 0x34 0x56 0x78
    0x12 0x34 0x56 0x78 0x12 0x34 0x56 0x78
    0x12 0x34 0x56 0x78 0x12 0x34 0x56 0x78
    ]))


(fun test2 [] void :
    (@ref let! bs auto (rec_val bitstream::Stream32 [(field_val Data123)]))
    (test::AssertEq# (bitstream::Stream32GetBits [(&! bs) 4]) 2_u32)
    (test::AssertEq# (bitstream::Stream32GetBits [(&! bs) 32])
      0x27856341_u32)

)

@cdecl (fun main [(param argc s32) (param argv (ptr (ptr u8)))] s32 :


    (shed (test1 []))
    (shed (test2 []))

    @doc "test end"
    (test::Success#)
    (return 0))

)