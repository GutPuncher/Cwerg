(module large_args [] [

(defrec pub MyRec [
    (field s1 s32 undef)
    (field s2 u32 undef)
    (field s3 u32 undef)
])


(fun foo [(param p1 u8) (param p2 MyRec) (param p3 bool) (param p4 MyRec)] MyRec [
    (return (? p3 p2 p4))
])


(fun bar [(param p1 bool) (param p2 MyRec) (param p3 MyRec)] MyRec [
    (return (call foo ['c' p2 p1 p3]))
])

])