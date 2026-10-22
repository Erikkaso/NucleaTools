"""Recompute validation-only INT8 calibration and reports without retraining."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'train_models'))
from train_multispeaker_v3 import metrics, predict, predict_int8, np, tf
from multispeaker_data import select_threshold, quiet_validation_mask


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    report = json.loads((output / 'results.json').read_text())
    manifest = json.loads((output / 'data_manifest.json').read_text())
    arrays = np.load(output / 'features.npz')
    model = tf.keras.models.load_model(output / 'nuclea_final.keras')
    interpreter = tf.lite.Interpreter(model_path=str(output / 'nuclea_int8.tflite'), num_threads=4)
    interpreter.allocate_tensors()
    val = predict_int8(interpreter, arrays['X_validation'])
    y = arrays['y_validation']
    quiet = quiet_validation_mask(manifest['validation'])
    previous = report['calibration']
    report['calibration'] = select_threshold(val[y == 1], val[y == 0], val[quiet])
    report['calibration_previous'] = previous
    threshold = report['calibration']['threshold']
    for split in ('validation', 'test'):
        x, y = arrays['X_' + split], arrays['y_' + split]
        scores = val if split == 'validation' else predict_int8(interpreter, x)
        float_scores = predict(model, x)
        report[split]['float'] = metrics(float_scores, y, threshold)
        report[split]['int8'] = metrics(scores, y, threshold)
        for speaker in report[split]['per_source']:
            mask = np.array([r['speaker'] == speaker for r in manifest[split]])
            report[split]['per_source'][speaker] = metrics(scores[mask], y[mask], threshold)
    mask = np.array([r['label'] == 1 and r['variant'] == 'clean' and r['speaker'] != 'synthetic'
                     for r in manifest['train']])
    scores = predict_int8(interpreter, arrays['X_train'][mask])
    rows = [r for r, keep in zip(manifest['train'], mask) if keep]
    diagnostics = {}
    for speaker in sorted({r['speaker'] for r in rows}):
        selected = np.array([r['speaker'] == speaker for r in rows])
        diagnostics[speaker] = metrics(scores[selected], np.ones(sum(selected)), threshold)
    report['training_positive_diagnostic_NOT_generalization'] = diagnostics
    report['silence_sanity']['passed'] = bool(np.all(np.array(report['silence_sanity']['zero_dc_scores']) < threshold))
    (output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps({'calibration': report['calibration'], 'test': report['test']['int8'],
                      'training_diagnostic': diagnostics}, indent=2), flush=True)


if __name__ == '__main__':
    main()
