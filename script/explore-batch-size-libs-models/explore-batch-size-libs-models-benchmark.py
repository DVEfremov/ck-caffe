import ck.kernel as ck
import copy
import re

# Batch size iteration parameters and number of repetitions.
p={'start':2,
   'step':2,
   'stop':16,
   'default':2,
   'repeat':3}

def do(i):
    # Detect basic platform info.
    ii={'action':'detect',
        'module_uoa':'platform',
        'out':'out'}
    r=ck.access(ii)
    if r['return']>0: return r

    # Host and target OS params.
    hos=r['host_os_uoa']
    hosd=r['host_os_dict']

    tos=r['os_uoa']
    tosd=r['os_dict']
    tdid=r['device_id']

    # Load Caffe program meta and desc to check deps.
    ii={'action':'load',
        'module_uoa':'program',
        'data_uoa':'caffe'}
    rx=ck.access(ii)
    if rx['return']>0: return rx
    mm=rx['dict']

    # Update deps from GPGPU or ones remembered during autotuning.
    cdeps=mm.get('compile_deps',{})

    # Caffe libs.
    depl=copy.deepcopy(cdeps['lib-caffe'])

    ii={'action':'resolve',
        'module_uoa':'env',
        'host_os':hos,
        'target_os':tos,
        'device_id':tdid,
        'deps':{'lib-caffe':copy.deepcopy(depl)}
    }
    r=ck.access(ii)
    if r['return']>0: return r

    udepl=r['deps']['lib-caffe'].get('choices',[]) # All UOAs of env for Caffe libs.
    if len(udepl)==0:
        return {'return':1, 'error':'no installed Caffe libs'}

    # Caffe models.
    depm=copy.deepcopy(cdeps['caffemodel'])

    ii={'action':'resolve',
        'module_uoa':'env',
        'host_os':hos,
        'target_os':tos,
        'device_id':tdid,
        'deps':{'caffemodel':copy.deepcopy(depm)}
    }
    r=ck.access(ii)
    if r['return']>0: return r

    udepm=r['deps']['caffemodel'].get('choices',[]) # All UOAs of env for Caffe models.
    if len(udepm)==0:
        return {'return':1, 'error':'no installed Caffe models'}

    # Prepare pipeline.
    cdeps['lib-caffe']['uoa']=udepl[0]
    cdeps['caffemodel']['uoa']=udepm[0]

    ii={'action':'pipeline',

        'module_uoa':'program',
        'data_uoa':'caffe',

        'prepare':'yes',

        'dependencies': cdeps,

        'no_state_check':'yes',
        'no_compiler_description':'yes',
        'skip_calibration':'yes',

        'cmd_key':'time_gpu',

        'cpu_freq':'max',
        'gpu_freq':'max',

        'speed':'yes',
        'energy':'no',

        'out':'con',
        'skip_print_timers':'yes'
    }

    r=ck.access(ii)
    if r['return']>0: return r

    fail=r.get('fail','')
    if fail=='yes':
        return {'return':10, 'error':'pipeline failed ('+r.get('fail_reason','')+')'}

    ready=r.get('ready','')
    if ready!='yes':
        return {'return':11, 'error':'pipeline not ready'}

    state=r['state']
    tmp_dir=state['tmp_dir']

    # Remember resolved deps for this benchmarking session.
    xcdeps=r.get('dependencies',{})

    # Clean pipeline.
    if 'ready' in r: del(r['ready'])
    if 'fail' in r: del(r['fail'])
    if 'return' in r: del(r['return'])

    pipeline=copy.deepcopy(r)

    # For each Caffe lib.
    for lib_uoa in udepl:
        # Load Caffe lib.
        ii={'action':'load',
            'module_uoa':'env',
            'data_uoa':lib_uoa}
        r=ck.access(ii)
        if r['return']>0: return r
        # Get the tags from e.g. 'BVLC Caffe framework (libdnn,viennacl)'
        lib_name=r['data_name']
        lib_tags=re.match('BVLC Caffe framework \((?P<tags>.*)\)', lib_name)
        lib_tags=lib_tags.group('tags').replace(' ', '').replace(',', '-')
        # Skip some libs with "in [..]" or "not in [..]".
        if lib_tags in []: continue

        # Use the 'time_cpu' command for the CPU only lib, 'time_gpu' for all the rest.
        if r['dict']['customize']['params']['cpu_only']==1:
            cmd_key='time_cpu'
        else:
            cmd_key='time_gpu'
        # FIXME: Customise cmd for NVIDIA's experimental fp16 branch.
        if lib_tags in ['nvidia-fp16-cuda','nvidia-fp16-emu-cuda','nvidia-fp16-cudnn','nvidia-fp16-emu-cudnn']:
            cmd_key='time_gpu_fp16'

        # For each Caffe model.
        for model_uoa in udepm:
            # Load Caffe model.
            ii={'action':'load',
                'module_uoa':'env',
                'data_uoa':model_uoa}
            r=ck.access(ii)
            if r['return']>0: return r
            # Get the tags from e.g. 'Caffe model (net and weights) (deepscale, squeezenet, 1.1)'
            model_name=r['data_name']
            model_tags = re.match('Caffe model \(net and weights\) \((?P<tags>.*)\)', model_name)
            model_tags = model_tags.group('tags').replace(' ', '').replace(',', '-')
            # Skip some models with "in [..]" or "not in [..]".
            if model_tags in []: continue

            record_repo='local'
            record_uoa=model_tags+'-'+lib_tags

            # Prepare pipeline.
            ck.out('---------------------------------------------------------------------------------------')
            ck.out('%s - %s' % (lib_name, lib_uoa))
            ck.out('%s - %s' % (model_name, model_uoa))
            ck.out('Experiment - %s:%s' % (record_repo, record_uoa))

            # Prepare autotuning input.
            cpipeline=copy.deepcopy(pipeline)

            # Reset deps and change UOA.
            new_deps={'lib-caffe':copy.deepcopy(depl),
                      'caffemodel':copy.deepcopy(depm)}

            new_deps['lib-caffe']['uoa']=lib_uoa
            new_deps['caffemodel']['uoa']=model_uoa

            jj={'action':'resolve',
                'module_uoa':'env',
                'host_os':hos,
                'target_os':tos,
                'device_id':tdid,
                'deps':new_deps}
            r=ck.access(jj)
            if r['return']>0: return r

            cpipeline['dependencies'].update(new_deps)

            cpipeline['cmd_key']=cmd_key

            ii={'action':'autotune',

                'module_uoa':'pipeline',
                'data_uoa':'program',

                'choices_order':[
                    [
                        '##env#CK_CAFFE_BATCH_SIZE'
                    ]
                ],
                'choices_selection':[
                    {'type':'loop', 'start':p['start'], 'stop':p['stop'], 'step':p['step'], 'default':p['default']}
                ],

                'features_keys_to_process':['##choices#*'],

                'iterations':-1,
                'repetitions':p['repeat'],

                'record':'yes',
                'record_failed':'yes',
                'record_params':{
                    'search_point_by_features':'yes'
                },
                'record_repo':record_repo,
                'record_uoa':record_uoa,

                'tags':['explore-batch-size-libs-models', cmd_key, model_tags, lib_tags],

                'pipeline':cpipeline,
                'out':'con'}

            r=ck.access(ii)
            if r['return']>0: return r

            fail=r.get('fail','')
            if fail=='yes':
                return {'return':10, 'error':'pipeline failed ('+r.get('fail_reason','')+')'}

    return {'return':0}

r=do({})
if r['return']>0: ck.err(r)
