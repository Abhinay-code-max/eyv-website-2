import React, { useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import axios from 'axios';
import { motion, AnimatePresence } from 'framer-motion';
import {
  ArrowLeft, Upload, FileText, Ticket, Wallet, Trash2, Eye, X,
  Plus, FilePlus, CheckCircle2,
} from 'lucide-react';
import { API_URL } from '../constants';
import { WALLET } from '../constants/testIds';
import EYVLogo from '../components/EYVLogo';
import { Button } from '../components/ui/button';
import { Input } from '../components/ui/input';
import { Label } from '../components/ui/label';

const CATEGORIES = [
  { value: 'boarding_pass', label: 'Boarding Pass', icon: Ticket },
  { value: 'ticket',        label: 'Ticket',        icon: Ticket },
  { value: 'voucher',       label: 'Voucher',       icon: FileText },
  { value: 'document',      label: 'Document',      icon: FileText },
];

const fadeUp = {
  hidden: { opacity: 0, y: 20 },
  show: (i = 0) => ({
    opacity: 1, y: 0,
    transition: { duration: 0.5, delay: i * 0.07, ease: [0.22, 1, 0.36, 1] },
  }),
};

const WalletPage = ({ user }) => {
  const navigate = useNavigate();
  const fileInputRef = useRef(null);
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showUpload, setShowUpload] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [previewItem, setPreviewItem] = useState(null);
  const [previewUrl, setPreviewUrl] = useState(null);
  const [activeCategory, setActiveCategory] = useState('all');
  const [dragOver, setDragOver] = useState(false);

  const [uploadForm, setUploadForm] = useState({
    file: null, title: '', category: 'document', description: '',
  });

  useEffect(() => { fetchItems(); }, []);

  /* ── all API calls preserved verbatim ── */
  const fetchItems = async () => {
    try {
      const response = await axios.get(`${API_URL}/wallet`, { withCredentials: true });
      setItems(response.data.items);
    } catch (error) { console.error('Error fetching wallet:', error); }
    finally { setLoading(false); }
  };

  const handleFileChange = (e) => {
    const file = e.target.files[0];
    if (file) setUploadForm({ ...uploadForm, file, title: uploadForm.title || file.name });
  };

  const handleDrop = (e) => {
    e.preventDefault(); setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file) setUploadForm({ ...uploadForm, file, title: uploadForm.title || file.name });
  };

  const handleUpload = async () => {
    if (!uploadForm.file) { alert('Please select a file'); return; }
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', uploadForm.file);
      const params = new URLSearchParams({
        category: uploadForm.category, title: uploadForm.title, description: uploadForm.description,
      });
      await axios.post(`${API_URL}/wallet/upload?${params.toString()}`, formData, {
        withCredentials: true, headers: { 'Content-Type': 'multipart/form-data' },
      });
      setShowUpload(false);
      setUploadForm({ file: null, title: '', category: 'document', description: '' });
      fetchItems();
    } catch (error) { console.error('Upload error:', error); alert('Failed to upload file'); }
    finally { setUploading(false); }
  };

  const handleDelete = async (itemId) => {
    if (!window.confirm('Delete this item from your wallet?')) return;
    try {
      await axios.delete(`${API_URL}/wallet/${itemId}`, { withCredentials: true });
      fetchItems();
    } catch (error) { console.error('Delete error:', error); }
  };

  const handlePreview = async (item) => {
    setPreviewItem(item);
    try {
      const response = await axios.get(`${API_URL}/wallet/${item.item_id}/download`, {
        withCredentials: true, responseType: 'blob',
      });
      setPreviewUrl(URL.createObjectURL(response.data));
    } catch (error) { console.error('Preview error:', error); alert('Failed to load preview'); }
  };

  const closePreview = () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setPreviewUrl(null); setPreviewItem(null);
  };

  const filteredItems = activeCategory === 'all'
    ? items
    : items.filter(item => item.category === activeCategory);

  const getCategoryIcon = (category) => {
    const cat = CATEGORIES.find(c => c.value === category);
    return cat ? cat.icon : FileText;
  };

  return (
    <motion.div
      data-testid={WALLET.walletContainer}
      className="min-h-screen bg-[#FDFBF7]"
      initial={{ opacity: 0 }} animate={{ opacity: 1 }} transition={{ duration: 0.4 }}
    >
      {/* Header */}
      <motion.div initial={{ y: -60, opacity: 0 }} animate={{ y: 0, opacity: 1 }}
        className="sticky top-0 z-50 bg-[#FDFBF7]/80 backdrop-blur-xl border-b border-[#E7E5E4] shadow-sm">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-4">
            <Button onClick={() => navigate('/dashboard')} variant="ghost"
              className="text-[#57534E] hover:text-[#C47245] transition-colors">
              <ArrowLeft size={20} />
            </Button>
            <EYVLogo size="small" />
          </div>
          <h2 className="text-2xl font-medium text-[#2A4B5C]"
            style={{ fontFamily: 'Cormorant Garamond, serif' }}>Travel Wallet</h2>
        </div>
      </motion.div>

      <div className="max-w-7xl mx-auto px-6 py-8">
        {/* Page heading */}
        <motion.div variants={fadeUp} initial="hidden" animate="show"
          className="flex items-start justify-between mb-8 flex-wrap gap-4">
          <div>
            <h1 className="text-4xl font-semibold text-[#1C1917]"
              style={{ fontFamily: 'Cormorant Garamond, serif' }}>
              Your Travel Documents
            </h1>
            <p className="text-[#57534E] mt-2">Store boarding passes, tickets, and vouchers in one place</p>
          </div>
          <motion.div whileHover={{ scale: 1.03 }} whileTap={{ scale: 0.97 }}>
            <Button data-testid={WALLET.uploadButton} onClick={() => setShowUpload(true)}
              className="bg-[#C47245] hover:bg-[#A85D38] hover:shadow-lg transition-all gap-2">
              <Plus size={18} /> Add Document
            </Button>
          </motion.div>
        </motion.div>

        {/* Category filter pills */}
        <motion.div variants={fadeUp} custom={1} initial="hidden" animate="show"
          className="flex gap-2 mb-6 flex-wrap">
          {[{ value: 'all', label: `All (${items.length})`, icon: null }, ...CATEGORIES.map(c => ({
            ...c, label: `${c.label} (${items.filter(i => i.category === c.value).length})`,
          }))].map(cat => (
            <motion.button key={cat.value} onClick={() => setActiveCategory(cat.value)}
              whileHover={{ y: -2 }} whileTap={{ scale: 0.96 }}
              className={`px-4 py-2 rounded-full text-sm font-medium transition-all flex items-center gap-1.5 ${
                activeCategory === cat.value
                  ? 'bg-[#C47245] text-white shadow-md shadow-[#C47245]/30'
                  : 'bg-white text-[#57534E] border border-[#E7E5E4] hover:border-[#C47245]/40'
              }`}>
              {cat.icon && <cat.icon size={13} />}
              {cat.label}
            </motion.button>
          ))}
        </motion.div>

        {/* Items */}
        {loading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {[1, 2, 3].map(i => (
              <div key={i} className="bg-white rounded-2xl overflow-hidden border border-[#E7E5E4] animate-pulse">
                <div className="h-40 bg-[#F5F2EB]" />
                <div className="p-4 space-y-3">
                  <div className="h-5 bg-[#E7E5E4] rounded w-2/3" />
                  <div className="h-3 bg-[#E7E5E4] rounded w-full" />
                  <div className="h-8 bg-[#E7E5E4] rounded mt-4" />
                </div>
              </div>
            ))}
          </div>
        ) : filteredItems.length === 0 ? (
          <motion.div variants={fadeUp} initial="hidden" animate="show"
            className="text-center py-20 bg-white rounded-3xl border border-dashed border-[#E7E5E4]">
            <div className="w-20 h-20 rounded-full bg-[#C47245]/10 flex items-center justify-center mx-auto mb-4">
              <Wallet size={36} className="text-[#C47245]" />
            </div>
            <p className="text-[#57534E] text-lg mb-2">
              {activeCategory === 'all' ? 'Your wallet is empty' : `No ${activeCategory.replace('_', ' ')}s yet`}
            </p>
            <Button onClick={() => setShowUpload(true)}
              className="mt-2 bg-[#C47245] hover:bg-[#A85D38] hover:shadow-lg transition-all gap-2">
              <FilePlus size={18} /> Upload Your First Document
            </Button>
          </motion.div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            <AnimatePresence>
              {filteredItems.map((item, idx) => {
                const Icon = getCategoryIcon(item.category);
                return (
                  <motion.div key={item.item_id} data-testid={WALLET.walletItem}
                    variants={fadeUp} custom={idx % 3} initial="hidden" animate="show"
                    exit={{ opacity: 0, scale: 0.9 }}
                    whileHover={{ y: -6, boxShadow: '0 20px 50px -16px rgba(28,25,23,0.15)' }}
                    className="bg-white rounded-2xl overflow-hidden border border-[#E7E5E4] transition-all group">
                    <div className="h-40 bg-gradient-to-br from-[#C47245]/10 to-[#E8B273]/20 flex items-center justify-center relative overflow-hidden">
                      {/* Subtle shimmer */}
                      <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent -translate-x-full group-hover:translate-x-full transition-transform duration-700" />
                      <motion.div whileHover={{ scale: 1.15, rotate: 8 }} transition={{ type: 'spring', stiffness: 300 }}>
                        <Icon size={48} className="text-[#C47245]" />
                      </motion.div>
                      <div className="absolute top-3 right-3 bg-white/90 backdrop-blur-sm px-2.5 py-1 rounded-full text-xs text-[#57534E] uppercase tracking-wider border border-white">
                        {item.category.replace('_', ' ')}
                      </div>
                    </div>
                    <div className="p-4">
                      <h3 className="font-medium text-[#1C1917] truncate mb-1"
                        style={{ fontFamily: 'Cormorant Garamond, serif', fontSize: '1.15rem' }}>
                        {item.title}
                      </h3>
                      {item.description && (
                        <p className="text-sm text-[#57534E] mb-2 line-clamp-2">{item.description}</p>
                      )}
                      <p className="text-xs text-[#86A8B3] mb-3">
                        {new Date(item.created_at).toLocaleDateString()} · {(item.size / 1024).toFixed(1)} KB
                      </p>
                      <div className="flex gap-2">
                        <Button onClick={() => handlePreview(item)} variant="outline" size="sm"
                          className="flex-1 hover:border-[#C47245] hover:text-[#C47245] transition-all gap-1">
                          <Eye size={14} /> View
                        </Button>
                        <motion.div whileHover={{ scale: 1.05 }} whileTap={{ scale: 0.95 }}>
                          <Button data-testid={WALLET.deleteItem} onClick={() => handleDelete(item.item_id)}
                            variant="outline" size="sm"
                            className="text-[#57534E] hover:text-red-500 hover:border-red-200 hover:bg-red-50 transition-all">
                            <Trash2 size={14} />
                          </Button>
                        </motion.div>
                      </div>
                    </div>
                  </motion.div>
                );
              })}
            </AnimatePresence>
          </div>
        )}
      </div>

      {/* Upload Modal */}
      <AnimatePresence>
        {showUpload && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
            onClick={() => setShowUpload(false)}>
            <motion.div
              initial={{ scale: 0.92, opacity: 0, y: 20 }}
              animate={{ scale: 1, opacity: 1, y: 0 }}
              exit={{ scale: 0.92, opacity: 0, y: 20 }}
              transition={{ type: 'spring', stiffness: 300, damping: 25 }}
              className="bg-white rounded-3xl p-8 max-w-md w-full shadow-2xl"
              onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-6">
                <h3 className="text-2xl font-medium text-[#1C1917]"
                  style={{ fontFamily: 'Cormorant Garamond, serif' }}>Add to Wallet</h3>
                <button onClick={() => setShowUpload(false)}
                  className="text-[#57534E] hover:text-[#1C1917] hover:bg-[#F5F2EB] p-1.5 rounded-full transition-all">
                  <X size={22} />
                </button>
              </div>
              <div className="space-y-4">
                {/* Drop zone */}
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">File (Max 10MB)</Label>
                  <div
                    onClick={() => fileInputRef.current?.click()}
                    onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
                    onDragLeave={() => setDragOver(false)}
                    onDrop={handleDrop}
                    className={`mt-2 border-2 border-dashed rounded-2xl p-6 text-center cursor-pointer transition-all ${
                      dragOver
                        ? 'border-[#C47245] bg-[#C47245]/5 scale-[1.02]'
                        : uploadForm.file
                        ? 'border-green-400 bg-green-50'
                        : 'border-[#E7E5E4] hover:border-[#C47245]/60 hover:bg-[#F5F2EB]'
                    }`}>
                    {uploadForm.file ? (
                      <div className="flex items-center justify-center gap-2 text-green-600">
                        <CheckCircle2 size={24} />
                        <span className="text-sm font-medium">{uploadForm.file.name}</span>
                      </div>
                    ) : (
                      <>
                        <Upload size={30} className="mx-auto text-[#C47245] mb-2" />
                        <p className="text-sm text-[#57534E]">Click or drag & drop (PDF, JPG, PNG)</p>
                      </>
                    )}
                    <input ref={fileInputRef} data-testid={WALLET.uploadFile} type="file"
                      onChange={handleFileChange} accept=".pdf,.jpg,.jpeg,.png,.gif,.webp" className="hidden" />
                  </div>
                </div>
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">Title</Label>
                  <Input data-testid={WALLET.uploadTitle} value={uploadForm.title}
                    onChange={(e) => setUploadForm({ ...uploadForm, title: e.target.value })}
                    placeholder="e.g., Maldives Boarding Pass"
                    className="mt-1 border-[#E7E5E4] focus:border-[#C47245] transition-colors" />
                </div>
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">Category</Label>
                  <div className="grid grid-cols-2 gap-2 mt-2">
                    {CATEGORIES.map(cat => (
                      <motion.button key={cat.value}
                        data-testid={`${WALLET.uploadCategory}-${cat.value}`}
                        onClick={() => setUploadForm({ ...uploadForm, category: cat.value })}
                        whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}
                        className={`p-3 rounded-xl border-2 transition-all flex items-center gap-2 ${
                          uploadForm.category === cat.value
                            ? 'border-[#C47245] bg-[#C47245]/10'
                            : 'border-[#E7E5E4] hover:border-[#C47245]/40'
                        }`}>
                        <cat.icon size={16} className="text-[#C47245]" />
                        <span className="text-sm text-[#1C1917]">{cat.label}</span>
                      </motion.button>
                    ))}
                  </div>
                </div>
                <div>
                  <Label className="text-xs uppercase tracking-wider text-[#C47245] font-medium">Description (Optional)</Label>
                  <Input value={uploadForm.description}
                    onChange={(e) => setUploadForm({ ...uploadForm, description: e.target.value })}
                    placeholder="Add notes..."
                    className="mt-1 border-[#E7E5E4] focus:border-[#C47245] transition-colors" />
                </div>
              </div>
              <div className="flex gap-3 mt-6">
                <Button onClick={() => setShowUpload(false)} variant="outline" className="flex-1 rounded-xl">
                  Cancel
                </Button>
                <Button data-testid={WALLET.uploadSubmit} onClick={handleUpload}
                  disabled={uploading || !uploadForm.file}
                  className="flex-1 bg-[#C47245] hover:bg-[#A85D38] rounded-xl hover:shadow-lg transition-all active:scale-95">
                  {uploading ? 'Uploading...' : 'Upload'}
                </Button>
              </div>
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>

      {/* Preview Modal */}
      <AnimatePresence>
        {previewItem && (
          <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }}
            className="fixed inset-0 z-50 bg-black/80 backdrop-blur-sm flex items-center justify-center p-4"
            onClick={closePreview}>
            <motion.div
              initial={{ scale: 0.92, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              exit={{ scale: 0.92, opacity: 0 }}
              transition={{ type: 'spring', stiffness: 300, damping: 25 }}
              className="bg-white rounded-3xl p-6 max-w-4xl max-h-[90vh] overflow-auto w-full shadow-2xl"
              onClick={(e) => e.stopPropagation()}>
              <div className="flex items-center justify-between mb-4">
                <h3 className="text-xl font-medium text-[#1C1917]"
                  style={{ fontFamily: 'Cormorant Garamond, serif' }}>{previewItem.title}</h3>
                <button onClick={closePreview}
                  className="text-[#57534E] hover:text-[#1C1917] hover:bg-[#F5F2EB] p-1.5 rounded-full transition-all">
                  <X size={22} />
                </button>
              </div>
              {previewUrl ? (
                previewItem.content_type?.startsWith('image/') ? (
                  <img src={previewUrl} alt={previewItem.title} className="w-full h-auto rounded-xl" />
                ) : previewItem.content_type === 'application/pdf' ? (
                  <iframe src={previewUrl} title="PDF Preview" className="w-full h-[70vh] rounded-xl" />
                ) : (
                  <div className="text-center py-12">
                    <a href={previewUrl} download={previewItem.original_filename}
                      className="text-[#C47245] underline hover:text-[#A85D38] transition-colors">
                      Download {previewItem.original_filename}
                    </a>
                  </div>
                )
              ) : (
                <div className="flex items-center justify-center py-12">
                  <div className="animate-spin h-12 w-12 border-4 border-[#C47245] border-t-transparent rounded-full" />
                </div>
              )}
            </motion.div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  );
};

export default WalletPage;
